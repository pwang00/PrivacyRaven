import pytorch_lightning as pl
import torch
from torch import nn
from torch.nn import functional as nnf
from torch import topk, add, log as vlog, tensor, sort
from tqdm import tqdm
from torch.cuda import device_count

class InversionModel(pl.LightningModule):
    def __init__(self, hparams, inversion_params, classifier):
        super().__init__()

        self.classifier = classifier
        self.hparams = hparams
        #self.save_hyperparameters()
        self.nz = inversion_params["nz"]
        self.ngf = inversion_params["ngf"]
        self.c = inversion_params["affine_shift"]
        self.t = inversion_params["truncate"]
        self.mse_loss = 0

        # Forces the classifier into evaluation mode
        self.classifier.eval()

        # Forces the inversion model into training mode
        self.train()

        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(
                self.nz,
                self.ngf * 4,
                stride=(1, 1), 
                kernel_size=(4, 4)
            ),
            nn.BatchNorm2d(self.ngf * 4),
            nn.Tanh(),

            nn.ConvTranspose2d(
                self.ngf * 4,
                self.ngf * 2,
                stride=(2, 2), 
                kernel_size=(4, 4),
                padding=(1, 1)
            ),

            nn.BatchNorm2d(self.ngf * 2),
            nn.Tanh(),
            
            nn.ConvTranspose2d(
                self.ngf * 2,
                self.ngf,
                stride=(2, 2), 
                kernel_size=(4, 4),
                padding=(1, 1)
            ),
            nn.BatchNorm2d(self.ngf),
            nn.Tanh(),

            nn.ConvTranspose2d(
                self.ngf,
                1,
                stride=(2, 2), 
                padding=(1, 1),
                kernel_size=(4, 4)
            ),

            nn.Sigmoid()

        )

    def training_step(self, batch, batch_idx):
        images, _ = batch

        for data in images:
            augmented = torch.empty(1, 1, 28, 28, device=self.device)
            augmented[0] = data

            Fwx = self.classifier(augmented)
            reconstructed = self(Fwx[0])
            augmented = nnf.pad(input=augmented, pad=(2, 2, 2, 2), value=data[0][0][0])
            loss = nnf.mse_loss(reconstructed, augmented)
            self.log("train_loss: ", loss)

        return loss

    def test_step(self, batch, batch_idx):
        images, _ = batch

        for data in images:
            augmented = torch.empty(1, 1, 28, 28, device=self.device)
            augmented[0] = data

            Fwx = self.classifier(augmented)
            reconstructed = self(Fwx[0])
            augmented = nnf.pad(input=augmented, pad=(2, 2, 2, 2), value=data[0][0][0])
            loss = nnf.mse_loss(reconstructed, augmented)
            self.log("test_loss: ", loss)

        return loss
        
    def forward(self, Fwx):
        z = torch.zeros(len(Fwx), device=self.device)
        topk, indices = torch.topk(Fwx, self.t)
        topk = torch.clamp(topk, min=-1e3) + self.c
        topk_min = topk.min()
        # We create a new vector of all zeros and place the top k entries in their original order
        Fwx = z.scatter_(0, indices, topk) + nnf.relu(-topk_min)
        Fwx = torch.reshape(Fwx, (10, 1))
        Fwx = Fwx.view(-1, self.nz, 1, 1)
        Fwx = self.decoder(Fwx)

        Fwx = Fwx.view(-1, 1, 32, 32)

        return Fwx
        

    def configure_optimizers(self):
        """Executes optimization for training and validation"""
        return torch.optim.Adam(self.parameters(), 1e-4)




