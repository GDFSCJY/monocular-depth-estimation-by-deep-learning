import argparse
import os
import yaml

import cv2
import albumentations as A
import albumentations.pytorch as AP

import torch
import torch.nn.functional as F

from utils import Cmapper

argparser = argparse.ArgumentParser()
argparser.add_argument("-c", "--config", type=str, default="configs/demo/demo.yml", help="path to config file")
argparser.add_argument("-p", "--photo", type=str, default=None, help="predict single photo")
args = argparser.parse_args()

# read yml file
print("config file: ", args.config)
if args.photo is not None:
    print("predict photo: ", args.photo)

with open(args.config, "r") as f:
    config = yaml.load(f, Loader=yaml.FullLoader)

device = config["device"]
torch_num_threads = config["torch_num_threads"]
resolution = config["resolution"]

fps = config["fps"]
model_path = config["model_path"]

torch.set_num_threads(torch_num_threads)
torch.set_grad_enabled(False)

# transforms
transforms = A.Compose([
    A.Resize(*resolution),
    A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    AP.ToTensorV2()
])

# cmapper
cmapper = Cmapper(cmap="plasma", maximum=10.0, minimum=0.0)

# model
model = torch.load(model_path)
model = model.to(device)
model.eval()
# model = torch.jit.script(model)

def predict(image):
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image = transforms(image=image)["image"]
    image = image.unsqueeze(0).to(device)
    pred = model(image)
    pred = F.interpolate(pred, scale_factor=3, mode="bilinear", align_corners=True)
    pred = pred[0, 0].cpu().numpy()
    pred = cmapper(pred)
    pred = cv2.cvtColor(pred, cv2.COLOR_RGB2BGR)
    return pred

# capture video
if args.photo is None:
    capture = cv2.VideoCapture(0)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[0])
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[1])
    capture.set(cv2.CAP_PROP_FPS, fps)

    while True:
        # read frame
        ret, image = capture.read()
        if not ret:
            raise RuntimeError("failed to read frame")
        # predict
        pred = predict(image)
        # display
        cv2.imshow("frame", image)
        cv2.imshow("pred", pred)

        # exit
        if cv2.waitKey(1) == ord("q"):
            break
else:
    image = cv2.imread(args.photo)
    pred = predict(image)
    cv2.imshow("frame", image)
    cv2.imshow("pred", pred)
    cv2.waitKey(0)