import os

import pandas as pd

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

import torchmetrics as tm

from utils.timer import Timer


class BaseTrainer:
    def __init__(self, model:nn, optimizer:optim=None, criterion=None, metrics=None, tensorboard_dir=""):
        self.model = model
        self.optimizer = optimizer
        self.criterion = criterion
        self.metrics = metrics

        self.loss_logger = tm.MeanMetric(full_state_update=False)
        self.writer = SummaryWriter(log_dir=os.path.join(tensorboard_dir, "logs"))
        self.timer = Timer()

        self.history = pd.DataFrame()
        self.device = "cpu"

    def set_train_mode(self, enable):
        if enable:
            self.model.train()
            torch.set_grad_enabled(True)
        else:
            self.model.eval()
            torch.set_grad_enabled(False)

    def to(self, device):
        self.device = device
        if self.model is not None:
            self.model.to(device)
        if self.criterion is not None:
            self.criterion.to(device)
        if self.metrics is not None:
            self.metrics.to(device)
        if self.loss_logger is not None:
            self.loss_logger.to(device)
        if self.optimizer is not None:
            for state in self.optimizer.state.values():
                for k, v in state.items():
                    if torch.is_tensor(v):
                        state[k] = v.to(device)

    def train_one_batch(self, image, y_true):
        image = image.to(self.device, dtype=torch.float32, non_blocking=True)
        y_true = y_true.to(self.device, dtype=torch.float32, non_blocking=True)

        self.optimizer.zero_grad(set_to_none=True)
        y_pred = self.model(image)
        loss = self.criterion(y_pred, y_true)
        loss.backward()
        self.optimizer.step()

        self.loss_logger(loss.detach())
        self.metrics.update(y_pred, y_true)

        return loss.detach()

    def val_one_batch(self, image, y_true):
        image = image.to(self.device, dtype=torch.float32, non_blocking=True)
        y_true = y_true.to(self.device, dtype=torch.float32, non_blocking=True)

        y_pred = self.model(image)
        loss = self.criterion(y_pred, y_true)

        self.loss_logger(loss.detach())
        self.metrics.update(y_pred, y_true)

        return loss.detach()

    def test_one_batch(self, image):
        image = image.to(self.device, dtype=torch.float32, non_blocking=True)
        y_pred = self.model(image)
        return y_pred

    def train_one_epoch(self, epoch, train_loader, val_loader, verbose=0):
        self.set_train_mode(True)
        self.timer.start()
        for i, (image, y_true, _) in enumerate(train_loader, 1):
            self.train_one_batch(image, y_true)
            if i % verbose == 0:
                print(f"Epoch {epoch} Training [{i}/{len(train_loader)}] [{self.timer(i, len(train_loader))}]")
        train_result = self.get_metrics_dict(prefix="train/", step=epoch)
        self.reset_metrics()

        self.set_train_mode(False)
        self.timer.start()
        for i, (image, y_true, _) in enumerate(val_loader, 1):
            self.val_one_batch(image, y_true)
            if i % verbose == 0:
                print(f"Epoch {epoch} Validating [{i}/{len(val_loader)}] [{self.timer(i, len(val_loader))}]")
        val_result = self.get_metrics_dict(prefix="val/", step=epoch)
        self.reset_metrics()

        # history
        lr = self.optimizer.param_groups[0]["lr"]
        result = {"Epoch": epoch, "lr": lr, **train_result, **val_result}
        self.history = self.history.append(result, ignore_index=True)

        return result

    def train(self, num_epochs, train_loader: DataLoader, val_loader: DataLoader, epoch_scheduler=None,
              verbose=0, save_checkpoint_per_num_epochs=0, checkpoints_dir=""):
        train_timer = Timer()
        for epoch in range(1, num_epochs + 1):
            print(f"Training {epoch}/{num_epochs} [[{train_timer(epoch, num_epochs)}]]")

            result = self.train_one_epoch(epoch, train_loader, val_loader, verbose)
            self.verbose(result)
            self.history_to_csv(os.path.join(checkpoints_dir, "history.csv"))

            if epoch_scheduler is not None:
                epoch_scheduler.step()

            if save_checkpoint_per_num_epochs > 0 and epoch % save_checkpoint_per_num_epochs == 0:
                self.save_checkpoint(os.path.join(checkpoints_dir, f"{epoch}_epoch.pkl"))

    def test(self, test_loader, verbose=0):
        self.set_train_mode(False)
        for i, (image, y_true, filenames) in enumerate(test_loader, 1):
            if i % verbose == 0:
                print(f"Testing [{i}/{len(test_loader)}] [{self.timer(i, len(test_loader))}]")
            yield self.test_one_batch(image), y_true, filenames

    def get_metrics_dict(self, prefix, step):
        time = self.timer.stop()

        loss = self.loss_logger.compute().cpu().item()
        self.writer.add_scalar(f"{prefix}loss", loss, step)

        self.metrics.prefix = prefix
        metrics = {}
        for name, metric in self.metrics.items():
            value = metric.compute().cpu().item()
            self.writer.add_scalar(name, value, step)
            metrics[name] = value

        return {f"{prefix}loss": loss, f"{prefix}time": int(time), **metrics}

    def reset_metrics(self):
        self.timer.reset()
        self.loss_logger.reset()
        self.metrics.reset()

    def history_to_csv(self, filename):
        self.history.to_csv(filename, index=False)

    def save_checkpoint(self, filename):
        print(f"Saving checkpoint to {filename}")
        checkpoints = {
            "model": self.model.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "history": self.history
        }
        torch.save(checkpoints, filename)

    def load_checkpoint(self, filename):
        checkpoints = torch.load(filename, map_location=self.device)
        if self.model is not None:
            self.model.load_state_dict(checkpoints["model"])
        if self.optimizer is not None:
            self.optimizer.load_state_dict(checkpoints["optimizer"])
        if self.history is not None:
            self.history = checkpoints["history"]
        return checkpoints

    def verbose(self, result):
        def _format(k, v):
            if isinstance(v, float):
                return f"{k}: {v:.4f}"
            return f"{k}: {v}"
        string = " - ".join([_format(k, v) for k, v in result.items()])
        print(string)
