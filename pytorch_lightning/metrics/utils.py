# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from typing import Tuple, Optional

import torch

from pytorch_lightning.utilities import rank_zero_warn

METRIC_EPS = 1e-6


def dim_zero_cat(x):
    return torch.cat(x, dim=0)


def dim_zero_sum(x):
    return torch.sum(x, dim=0)


def dim_zero_mean(x):
    return torch.mean(x, dim=0)


def _flatten(x):
    return [item for sublist in x for item in sublist]


def _check_same_shape(pred: torch.Tensor, target: torch.Tensor):
    """ Check that predictions and target have the same shape, else raise error """
    if pred.shape != target.shape:
        raise RuntimeError('Predictions and targets are expected to have the same shape')


def _input_format_classification(
        preds: torch.Tensor,
        target: torch.Tensor,
        threshold: float = 0.5
) -> Tuple[torch.Tensor, torch.Tensor]:
    """ Convert preds and target tensors into label tensors

    Args:
        preds: either tensor with labels, tensor with probabilities/logits or
            multilabel tensor
        target: tensor with ground true labels
        threshold: float used for thresholding multilabel input

    Returns:
        preds: tensor with labels
        target: tensor with labels
    """
    if not (len(preds.shape) == len(target.shape) or len(preds.shape) == len(target.shape) + 1):
        raise ValueError(
            "preds and target must have same number of dimensions, or one additional dimension for preds"
        )

    if len(preds.shape) == len(target.shape) + 1:
        # multi class probabilites
        preds = torch.argmax(preds, dim=1)

    if len(preds.shape) == len(target.shape) and preds.dtype == torch.float:
        # binary or multilabel probablities
        preds = (preds >= threshold).long()
    return preds, target


def _input_format_classification_one_hot(
        num_classes: int,
        preds: torch.Tensor,
        target: torch.Tensor,
        threshold: float = 0.5,
        multilabel: bool = False
) -> Tuple[torch.Tensor, torch.Tensor]:
    """ Convert preds and target tensors into one hot spare label tensors

    Args:
        num_classes: number of classes
        preds: either tensor with labels, tensor with probabilities/logits or
            multilabel tensor
        target: tensor with ground true labels
        threshold: float used for thresholding multilabel input
        multilabel: boolean flag indicating if input is multilabel

    Returns:
        preds: one hot tensor of shape [num_classes, -1] with predicted labels
        target: one hot tensors of shape [num_classes, -1] with true labels
    """
    if not (len(preds.shape) == len(target.shape) or len(preds.shape) == len(target.shape) + 1):
        raise ValueError(
            "preds and target must have same number of dimensions, or one additional dimension for preds"
        )

    if len(preds.shape) == len(target.shape) + 1:
        # multi class probabilites
        preds = torch.argmax(preds, dim=1)

    if len(preds.shape) == len(target.shape) and preds.dtype == torch.long and num_classes > 1 and not multilabel:
        # multi-class
        preds = to_onehot(preds, num_classes=num_classes)
        target = to_onehot(target, num_classes=num_classes)

    elif len(preds.shape) == len(target.shape) and preds.dtype == torch.float:
        # binary or multilabel probablities
        preds = (preds >= threshold).long()

    # transpose class as first dim and reshape
    if len(preds.shape) > 1:
        preds = preds.transpose(1, 0)
        target = target.transpose(1, 0)

    return preds.reshape(num_classes, -1), target.reshape(num_classes, -1)


def to_onehot(
        tensor: torch.Tensor,
        num_classes: Optional[int] = None,
) -> torch.Tensor:
    """
    Converts a dense label tensor to one-hot format

    Args:
        tensor: dense label tensor, with shape [N, d1, d2, ...]
        num_classes: number of classes C

    Output:
        A sparse label tensor with shape [N, C, d1, d2, ...]

    Example:

        >>> x = torch.tensor([1, 2, 3])
        >>> to_onehot(x)
        tensor([[0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1]])

    """
    if num_classes is None:
        num_classes = int(tensor.max().detach().item() + 1)
    dtype, device, shape = tensor.dtype, tensor.device, tensor.shape
    tensor_onehot = torch.zeros(shape[0], num_classes, *shape[1:],
                                dtype=dtype, device=device)
    index = tensor.long().unsqueeze(1).expand_as(tensor_onehot)
    return tensor_onehot.scatter_(1, index, 1.0)


def to_categorical(
        tensor: torch.Tensor,
        argmax_dim: int = 1
) -> torch.Tensor:
    """
    Converts a tensor of probabilities to a dense label tensor

    Args:
        tensor: probabilities to get the categorical label [N, d1, d2, ...]
        argmax_dim: dimension to apply

    Return:
        A tensor with categorical labels [N, d2, ...]

    Example:

        >>> x = torch.tensor([[0.2, 0.5], [0.9, 0.1]])
        >>> to_categorical(x)
        tensor([1, 0])

    """
    return torch.argmax(tensor, dim=argmax_dim)


def get_num_classes(
        pred: torch.Tensor,
        target: torch.Tensor,
        num_classes: Optional[int] = None,
) -> int:
    """
    Calculates the number of classes for a given prediction and target tensor.

    Args:
        pred: predicted values
        target: true labels
        num_classes: number of classes if known

    Return:
        An integer that represents the number of classes.
    """
    num_target_classes = int(target.max().detach().item() + 1)
    num_pred_classes = int(pred.max().detach().item() + 1)
    num_all_classes = max(num_target_classes, num_pred_classes)

    if num_classes is None:
        num_classes = num_all_classes
    elif num_classes != num_all_classes:
        rank_zero_warn(f'You have set {num_classes} number of classes which is'
                       f' different from predicted ({num_pred_classes}) and'
                       f' target ({num_target_classes}) number of classes',
                       RuntimeWarning)
    return num_classes


def reduce(to_reduce: torch.Tensor, reduction: str) -> torch.Tensor:
    """
    Reduces a given tensor by a given reduction method

    Args:
        to_reduce : the tensor, which shall be reduced
       reduction :  a string specifying the reduction method ('elementwise_mean', 'none', 'sum')

    Return:
        reduced Tensor

    Raise:
        ValueError if an invalid reduction parameter was given
    """
    if reduction == 'elementwise_mean':
        return torch.mean(to_reduce)
    if reduction == 'none':
        return to_reduce
    if reduction == 'sum':
        return torch.sum(to_reduce)
    raise ValueError('Reduction parameter unknown.')


def class_reduce(num: torch.Tensor,
                 denom: torch.Tensor,
                 weights: torch.Tensor,
                 class_reduction: str = 'none') -> torch.Tensor:
    """
    Function used to reduce classification metrics of the form `num / denom * weights`.
    For example for calculating standard accuracy the num would be number of
    true positives per class, denom would be the support per class, and weights
    would be a tensor of 1s

    Args:
        num: numerator tensor
        decom: denominator tensor
        weights: weights for each class
        class_reduction: reduction method for multiclass problems

            - ``'micro'``: calculate metrics globally (default)
            - ``'macro'``: calculate metrics for each label, and find their unweighted mean.
            - ``'weighted'``: calculate metrics for each label, and find their weighted mean.
            - ``'none'`` or ``None``: returns calculated metric per class

    """
    valid_reduction = ('micro', 'macro', 'weighted', 'none', None)
    if class_reduction == 'micro':
        fraction = torch.sum(num) / torch.sum(denom)
    else:
        fraction = num / denom

    # We need to take care of instances where the denom can be 0
    # for some (or all) classes which will produce nans
    fraction[fraction != fraction] = 0

    if class_reduction == 'micro':
        return fraction
    elif class_reduction == 'macro':
        return torch.mean(fraction)
    elif class_reduction == 'weighted':
        return torch.sum(fraction * (weights.float() / torch.sum(weights)))
    elif class_reduction == 'none' or class_reduction is None:
        return fraction

    raise ValueError(f'Reduction parameter {class_reduction} unknown.'
                     f' Choose between one of these: {valid_reduction}')
