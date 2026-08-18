import torch
from torch import nn
from torch.nn import functional as F

class FusedLeakyReLU(nn.Module):
    def __init__(self, channel, negative_slope=0.2, scale=2 ** 0.5):
        super().__init__()
        self.bias = nn.Parameter(torch.zeros(channel))
        self.negative_slope = negative_slope
        self.scale = scale

    def forward(self, input):
        return fused_leaky_relu(input, self.bias, self.negative_slope, self.scale)

def fused_leaky_relu(input, bias, negative_slope=0.2, scale=2 ** 0.5):
    if input.ndim == 4:
        bias_reshaped = bias.view(1, -1, 1, 1)
    elif input.ndim == 3:
        bias_reshaped = bias.view(1, -1, 1)
    elif input.ndim == 2:
        bias_reshaped = bias.view(1, -1)
    else:
        bias_reshaped = bias
    
    out = input + bias_reshaped
    out = F.leaky_relu(out, negative_slope=negative_slope)
    return out * scale
