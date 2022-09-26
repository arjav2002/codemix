import argparse
import torch

import pytorch_lightning as pl 
from pytorch_lightning.loggers import TensorBoardLogger, WandbLogger
from pytorch_lightning.utilities.seed import seed_everything
from pytorch_lightning.callbacks.early_stopping import EarlyStopping
from pytorch_lightning.callbacks import ModelCheckpoint

from src.models.baseline.baseline import BaseLine
from src.datamodules.lince import LinceDM

from config import (
    GLOBAL_SEED,
    MAX_EPOCHS,
    LEARNING_RATE,
    PATH_EXPERIMENTS,
    PATH_LINCE_DATASET,
    PROJECT_NAME,
    WARM_RESTARTS,
    WEIGHT_DECAY,
    DROPOUT_RATE,
    MAX_SEQUENCE_LENGTH,
    PADDING,
    BATCH_SIZE,
    BASE_MODEL,
    NUM_WORKERS,
    AVAIL_GPUS,
)

def test_dm(args):
    dm = LinceDM(
        model_name=args.base_model, 
        dataset_name=args.dataset, 
        batch_size=args.batch_size,
        max_seq_len=args.max_seq_len,
        padding=args.padding,
        num_workers=args.workers
    )

    dm.setup()
    print(next(iter(dm.train_dataloader())))


def main(args):
    
    # Set global seed 
    seed_everything(GLOBAL_SEED)

    # Init DM 
    dm = LinceDM(
        model_name=args.base_model, 
        dataset_name=args.dataset, 
        dataset_dir=args.dataset_dir,
        batch_size=args.batch_size,
        max_seq_len=args.max_seq_len,
        padding=args.padding,
        num_workers=args.workers
    )

    # Init Model 
    freeze = False
    if args.freeze == "freeze": 
        freeze=True

    print(freeze)

    model = BaseLine(
        model_name=args.base_model, 
        max_seq_len=args.max_seq_len, 
        padding=args.padding, 
        learning_rate=args.lr, 
        ner_learning_rate=args.ner_lr, 
        lid_learning_rate=args.lid_lr, 
        warm_restart_epochs=args.warm_restart_epochs,
        weight_decay=args.weight_decay,
        ner_wd=args.ner_wd,
        lid_wd=args.lid_wd,
        dropout_rate=args.dropout,
        freeze=freeze
    )

    # Init Logger & Trainer 
    
    logger = TensorBoardLogger(
        save_dir=PATH_EXPERIMENTS,
        name=args.run_name
    )

    if args.logger == "wandb":
        logger = WandbLogger(
            name=args.run_name, 
            save_dir=PATH_EXPERIMENTS,
            id=args.run_name,
            project=PROJECT_NAME,
        )

    es = EarlyStopping(
        monitor="f1/val-ner", 
        mode='max',
        patience=5,
    )

    cp = ModelCheckpoint(
        dirpath=args.checkpoint_path,
        filename=f"{args.base_model}" + "-{f1/val-ner: .4f}",
        monitor='f1/val-ner',
        save_top_k=3,
        mode='max',
    )

    trainer = pl.Trainer(
        max_epochs=args.epochs,
        accelerator="gpu",
        devices=args.gpus,
        logger=logger,
        log_every_n_steps=20,
        callbacks=[es, cp], 
        deterministic=True,        # Get same results on differnt GPUs ( hopefully )
    )

    # Runs
    trainer.fit(model, datamodule=dm)

if __name__=="__main__":
    parser = argparse.ArgumentParser()
    
    # Hyperparams
    parser.add_argument("--epochs", type=int, default=MAX_EPOCHS, help="Set max epochs")
    parser.add_argument("--lr", type=float, default=LEARNING_RATE, help="Set Learning Rate")
    parser.add_argument("--ner_lr", type=float, default=LEARNING_RATE, help="Set task learning rate")
    parser.add_argument("--lid_lr", type=float, default=LEARNING_RATE, help="Set task learning rate")
    parser.add_argument("--weight_decay", type=float, default=WEIGHT_DECAY, help="Set Weight Decay")
    parser.add_argument("--ner_wd", type=float, default=WEIGHT_DECAY, help="Set weight decay")
    parser.add_argument("--lid_wd", type=float, default=WEIGHT_DECAY, help="Set weight decay")
    parser.add_argument("--dropout", type=float, default=DROPOUT_RATE, help="Set dropout rate")
    parser.add_argument("--max_seq_len", type=int, default=MAX_SEQUENCE_LENGTH, help="Set max seq length")
    parser.add_argument("--padding", type=str, default=PADDING, help="Set padding style")
    parser.add_argument("--batch_size", type=int, default=BATCH_SIZE, help="Set batch size")
    parser.add_argument("--base_model", type=str, default=BASE_MODEL, help="Set base transformer model")
    parser.add_argument("--freeze", type=str, default="unfreeze", help="Freeze or Unfreeze base model")
    parser.add_argument("--warm_restart_epochs", type=str, default=WARM_RESTARTS, help="Set LR Scheduler Warmups")
    parser.add_argument("--dataset", type=str, default="lince", help="Set dataset to be used")
    parser.add_argument("--dataset_dir", type=str, default=PATH_LINCE_DATASET, help="Set datset directory")
    parser.add_argument("--run_name", type=str, required=True, help="Set run name per experiment")
    parser.add_argument("--logger", type=str, default="tensorboard", help="Set logging software")
    parser.add_argument("--checkpoint_path", type=str, default="./checkpoints", help="Set path to save models")

    # Hardware
    parser.add_argument("--workers", type=int, default=NUM_WORKERS, help="Set CPU Threads")
    parser.add_argument("--gpus", type=int, default=AVAIL_GPUS, help="Set no. of GPUs required")

    args = parser.parse_args()

    # test_dm(args)

    # Check for reproducibility on differnt GPUs
    # torch.use_deterministic_algorithms(True)

    main(args)