import torch
import torchmetrics as tm


class Log10AverageError(tm.MeanAbsoluteError):
    higher_is_better = False
    def __init__(self, full_state_update=False):
        super(Log10AverageError, self).__init__(full_state_update=full_state_update)

    def update(self, preds, target):
        preds = torch.clamp_min(preds, 1e-6)
        target = torch.clamp_min(target, 1e-6)
        super(Log10AverageError, self).update(torch.log10(preds), torch.log10(target))
