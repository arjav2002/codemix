from typing import Optional 

import torch 
import torch.nn as nn 
import torch.nn.functional as F 

import pytorch_lightning as pl
from pytorch_lightning.utilities.types import STEP_OUTPUT

from torchmetrics.functional import precision, recall, f1_score
from torchcrf import CRF

from src.modules.base_model import BaseModel

from config import (
    LABEL2ID,
    LEARNING_RATE,
    LID2ID, 
    WEIGHT_DECAY,
    DROPOUT_RATE,
    MAX_SEQUENCE_LENGTH,
    PADDING
)

class BaseLine(pl.LightningModule):
    def __init__(
        self, 
        model_name: str, 
        max_seq_len: int = MAX_SEQUENCE_LENGTH,
        padding: str = PADDING,
        label2id: dict = LABEL2ID,
        lid2id: dict = LID2ID,
        learning_rate: float = LEARNING_RATE, 
        ner_learning_rate: float = LEARNING_RATE,
        lid_learning_rate: float = LEARNING_RATE,
        weight_decay: float = WEIGHT_DECAY,
        dropout_rate: float = DROPOUT_RATE,
    ) -> None:

        super().__init__()
        self.save_hyperparameters()

        self.lid_pad_token_label = len(self.hparams.lid2id)
        self.ner_pad_token_label = len(self.hparams.label2id)

        # Shared params
        self.base_model = BaseModel(self.hparams.model_name)

        self.bi_lstm = nn.LSTM(
            input_size=self.base_model.model.config.hidden_size,
            hidden_size=256,
            batch_first=True,
            bidirectional=True
        )
        
        # NER Task params
        self.ner_net = nn.Sequential(
            nn.Linear(512, 128), 
            nn.LeakyReLU(), 
            nn.Linear(128, 32),
            nn.LeakyReLU(),
            nn.Linear(32, len(self.hparams.label2id) + 1)
        )

        self.ner_crf = CRF(
            num_tags=len(self.hparams.label2id) + 1,
            batch_first=True
        )

        # LID Task params 
        self.lid_net = nn.Sequential(
            nn.Linear(512, 128), 
            nn.LeakyReLU(), 
            nn.Linear(128, 32),
            nn.LeakyReLU(),
            nn.Linear(32, len(self.hparams.lid2id) + 1)
        )

        self.lid_crf = CRF(
            num_tags=len(self.hparams.lid2id) + 1,
            batch_first=True
        )


    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        base_model_outs = self.base_model(
            input_ids,
            attention_mask
        )

        base_outs = base_model_outs.last_hidden_state 
        lstm_outs, _ = self.bi_lstm(base_outs)
        
        # NER 
        ner_net_outs = self.ner_net(lstm_outs)

        # LID
        lid_net_outs = self.lid_net(lstm_outs)

        return ner_net_outs, lid_net_outs
    
    def training_step(self, batch, batch_idx) -> STEP_OUTPUT:
        input_ids = batch['input_ids']
        attention_mask = batch['attention_mask']
        labels = batch['labels']
        lids = batch['lids']

        ner_emissions, lid_emissions = self(input_ids, attention_mask)

        ner_loss = -self.ner_crf(ner_emissions, labels, attention_mask.bool())
        lid_loss = -self.lid_crf(lid_emissions, lids, attention_mask.bool())

        ner_path = self.ner_crf.decode(ner_emissions)
        ner_path = torch.tensor(ner_path, device=self.device).long()

        lid_path = self.lid_crf.decode(lid_emissions)
        lid_path = torch.tensor(lid_path, device=self.device).long()

        # Simply summing loss for now 
        # TODO: Weighted Loss
        loss = ner_loss + lid_loss 

        ner_metrics = self._compute_metrics(ner_path, labels, "train", "ner")
        lid_metrics = self._compute_metrics(lid_path, lids, "train", "lid")

        self.log("loss/train", loss)
        self.log("loss-ner/train", ner_loss)
        self.log("loss-lid/train", lid_loss)

        self.log_dict(ner_metrics, on_step=False, on_epoch=True)
        self.log_dict(lid_metrics, on_step=False, on_epoch=True)

        return loss

    
    def validation_step(self, batch, batch_idx) -> Optional[STEP_OUTPUT]:
        input_ids = batch['input_ids']
        attention_mask = batch['attention_mask']
        labels = batch['labels']
        lids = batch['lids']

        ner_emissions, lid_emissions = self(input_ids, attention_mask)

        ner_loss = -self.ner_crf(ner_emissions, labels, attention_mask.bool())
        lid_loss = -self.lid_crf(lid_emissions, lids, attention_mask.bool())

        ner_path = self.ner_crf.decode(ner_emissions)
        ner_path = torch.tensor(ner_path, device=self.device).long()

        lid_path = self.lid_crf.decode(lid_emissions)
        lid_path = torch.tensor(lid_path, device=self.device).long()

        loss = ner_loss + lid_loss 
        ner_metrics = self._compute_metrics(ner_path, labels, "val", "ner")
        lid_metrics = self._compute_metrics(lid_path, lids, "val", "lid")

        self.log("loss/val", loss)
        self.log("loss-ner/val", ner_loss)
        self.log("loss-lid/val", lid_loss)

        self.log_dict(ner_metrics, on_step=False, on_epoch=True)
        self.log_dict(lid_metrics, on_step=False, on_epoch=True)

    
    def configure_optimizers(self):
        
        # Same LR for shared params and different LR for different tasks params
        # Same weight decay for shared params and different weight decay for different tasks params 
        # TODO: Experiment with Different LRs
        
        no_decay = ["bias", "LayerNorm.weight"]

        optimizer_grouped_parameters = [
            {
                'params': [
                    p 
                    for n, p in self.base_model.named_parameters()
                    if not any(nd in n for nd in no_decay)
                ],
            },  
            {
                'params': [
                    p 
                    for n, p in self.bi_lstm.named_parameters()
                    if not any(nd in n for nd in no_decay)
                ],

            }, 
            {
                'params': [
                    p 
                    for n, p in self.ner_net.named_parameters()
                    if not any(nd in n for nd in no_decay)
                ],
                'lr': self.hparams.ner_learning_rate
            }, 
            {
                'params': [
                    p
                    for n, p in self.lid_net.named_parameters()
                    if not any(nd in n for nd in no_decay)
                ], 
                'lr': self.hparams.lid_learning_rate
            }, 
            {
                'params': [
                    p 
                    for n, p in self.named_parameters()
                    if any(nd in n for nd in no_decay)
                ], 
                'weight_decay': 0.0
            }
        ]

        optimizer = torch.optim.AdamW(
            params=optimizer_grouped_parameters, 
            lr=self.hparams.learning_rate,
            weight_decay=self.hparams.weight_decay
        )

        return optimizer
    

    def _compute_metrics(self, preds: torch.Tensor, targets: torch.Tensor, mode: str, task: str):
        preds = preds.reshape(-1, 1)
        preds.type_as(targets)            # Make preds tensor on same device as targets

        targets = targets.reshape(-1, 1)

        metrics = {}

        if task == "ner":
            metrics[f"prec/{mode}-{task}"] = precision(
                preds, targets, 
                average="macro", 
                num_classes=len(self.hparams.label2id) + 1, 
                ignore_index=self.ner_pad_token_label
            )
            
            metrics[f"rec/{mode}-{task}"] = recall(
                preds, targets, 
                average="macro", 
                num_classes=len(self.hparams.label2id) + 1,
                ignore_index=self.ner_pad_token_label
            )

            metrics[f"f1/{mode}-{task}"] = f1_score(
                preds, targets, 
                average="macro", 
                num_classes=len(self.hparams.label2id) + 1,
                ignore_index=self.ner_pad_token_label
            )

        elif task == "lid":
            metrics[f"prec/{mode}-{task}"] = precision(
                preds, targets, 
                average="macro", 
                num_classes=len(self.hparams.label2id) + 1, 
                ignore_index=self.lid_pad_token_label
            )
            metrics[f"rec/{mode}-{task}"] = recall(
                preds, targets, 
                average="macro", 
                num_classes=len(self.hparams.label2id) + 1, 
                ignore_index=self.lid_pad_token_label
            )

            metrics[f"f1/{mode}-{task}"] = f1_score(
                preds, targets, 
                average="macro", 
                num_classes=len(self.hparams.label2id) + 1, 
                ignore_index=self.lid_pad_token_label
            )

        return metrics 