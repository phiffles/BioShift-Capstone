import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import sys
import uuid
import torch
import torchvision.transforms as transforms
from PIL import Image
import numpy as np
import cv2
import scipy.ndimage

# Ensure SAM is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SAM_DIR = os.path.join(SCRIPT_DIR, "SAM")
if SAM_DIR not in sys.path:
    sys.path.append(SAM_DIR)

import dlib
from argparse import Namespace
from SAM.models.psp import pSp


class AgeTransformer:
    """Add the normalized target-age channel expected by the SAM encoder."""

    def __init__(self, target_age):
        self.target_age = target_age

    def __call__(self, img):
        target_age = int(self.target_age) / 100
        age_channel = target_age * torch.ones((1, img.shape[1], img.shape[2]))
        return torch.cat((img, age_channel))


def get_landmark(filepath, predictor):
    """Return the 68 dlib landmarks for the last detected face."""

    detector = dlib.get_frontal_face_detector()
    img = dlib.load_rgb_image(filepath)
    detections = detector(img, 1)
    shape = None
    for detection in detections:
        shape = predictor(img, detection)
    if shape is None:
        raise ValueError("Could not find a face in the image.")
    return np.array([[point.x, point.y] for point in shape.parts()])


def tensor2im(tensor):
    """Convert a SAM output tensor in [-1, 1] to a Pillow RGB image."""

    array = tensor.cpu().detach().transpose(0, 2).transpose(0, 1).numpy()
    array = np.clip((array + 1) / 2, 0, 1) * 255
    return Image.fromarray(array.astype("uint8"))


class FaceNotFoundError(Exception):
    """Raised when no face could be detected for alignment."""
    pass


def _align_face_with_quad(filepath, predictor):
    """
    Local re-implementation of the geometry in
    the original SAM FFHQ alignment routine (same dlib landmarks and
    shrink/crop/pad/QUAD-transform steps, so the 256x256 aligned crop fed to
    the neural net is unchanged) that additionally returns the aligned
    quad's 4 corners in the ORIGINAL image's pixel coordinates — captured
    before shrink/crop/pad translate/scale it — so the aged face can later
    be warped back into the original photo.

    Returns (aligned_256_img: PIL.Image, quad_orig: np.ndarray shape (4,2)).
    Raises FaceNotFoundError if no face is detected.
    """
    try:
        lm = get_landmark(filepath, predictor)
    except Exception as exc:
        raise FaceNotFoundError(str(exc)) from exc

    lm_eye_left = lm[36:42]
    lm_eye_right = lm[42:48]
    lm_mouth_outer = lm[48:60]

    eye_left = np.mean(lm_eye_left, axis=0)
    eye_right = np.mean(lm_eye_right, axis=0)
    eye_avg = (eye_left + eye_right) * 0.5
    eye_to_eye = eye_right - eye_left
    mouth_left = lm_mouth_outer[0]
    mouth_right = lm_mouth_outer[6]
    mouth_avg = (mouth_left + mouth_right) * 0.5
    eye_to_mouth = mouth_avg - eye_avg

    x = eye_to_eye - np.flipud(eye_to_mouth) * [-1, 1]
    x /= np.hypot(*x)
    x *= max(np.hypot(*eye_to_eye) * 2.0, np.hypot(*eye_to_mouth) * 1.8)
    y = np.flipud(x) * [-1, 1]
    c = eye_avg + eye_to_mouth * 0.1
    quad = np.stack([c - x - y, c - x + y, c + x + y, c + x - y])
    qsize = np.hypot(*x) * 2

    # Snapshot the quad in ORIGINAL image coordinates, before shrink/crop/pad
    # mutate it below. Translations/uniform-scale don't change this shape.
    quad_orig = quad.copy()

    img = Image.open(filepath).convert("RGB")

    output_size = 256
    transform_size = 256
    enable_padding = True

    # Shrink.
    shrink = int(np.floor(qsize / output_size * 0.5))
    if shrink > 1:
        rsize = (int(np.rint(float(img.size[0]) / shrink)), int(np.rint(float(img.size[1]) / shrink)))
        img = img.resize(rsize, Image.Resampling.LANCZOS)
        quad /= shrink
        qsize /= shrink

    # Crop.
    border = max(int(np.rint(qsize * 0.1)), 3)
    crop = (int(np.floor(min(quad[:, 0]))), int(np.floor(min(quad[:, 1]))), int(np.ceil(max(quad[:, 0]))),
            int(np.ceil(max(quad[:, 1]))))
    crop = (max(crop[0] - border, 0), max(crop[1] - border, 0), min(crop[2] + border, img.size[0]),
            min(crop[3] + border, img.size[1]))
    if crop[2] - crop[0] < img.size[0] or crop[3] - crop[1] < img.size[1]:
        img = img.crop(crop)
        quad -= crop[0:2]

    # Pad.
    pad = (int(np.floor(min(quad[:, 0]))), int(np.floor(min(quad[:, 1]))), int(np.ceil(max(quad[:, 0]))),
           int(np.ceil(max(quad[:, 1]))))
    pad = (max(-pad[0] + border, 0), max(-pad[1] + border, 0), max(pad[2] - img.size[0] + border, 0),
           max(pad[3] - img.size[1] + border, 0))
    if enable_padding and max(pad) > border - 4:
        pad = np.maximum(pad, int(np.rint(qsize * 0.3)))
        img = np.pad(np.float32(img), ((pad[1], pad[3]), (pad[0], pad[2]), (0, 0)), 'reflect')
        h, w, _ = img.shape
        yy, xx, _ = np.ogrid[:h, :w, :1]
        mask = np.maximum(1.0 - np.minimum(np.float32(xx) / pad[0], np.float32(w - 1 - xx) / pad[2]),
                          1.0 - np.minimum(np.float32(yy) / pad[1], np.float32(h - 1 - yy) / pad[3]))
        blur = qsize * 0.02
        img += (scipy.ndimage.gaussian_filter(img, [blur, blur, 0]) - img) * np.clip(mask * 3.0 + 1.0, 0.0, 1.0)
        img += (np.median(img, axis=(0, 1)) - img) * np.clip(mask, 0.0, 1.0)
        img = Image.fromarray(np.uint8(np.clip(np.rint(img), 0, 255)), 'RGB')
        quad += pad[:2]

    # Transform.
    img = img.transform((transform_size, transform_size), Image.QUAD, (quad + 0.5).flatten(), Image.BILINEAR)
    if output_size < transform_size:
        img = img.resize((output_size, output_size), Image.Resampling.LANCZOS)

    return img, quad_orig


def _composite_aged_face(original_img, aged_face_img, quad_orig):
    """
    Warp the aged face crop back onto the full-resolution original image
    using the affine mapping recovered from quad_orig, alpha-blended with a
    feathered oval mask. Only the face/head region changes — every pixel
    outside the oval is mathematically identical to the original.

    aged_face_img corresponds to the same aligned face region as the 256x256
    crop fed into the network, but the pSp/StyleGAN2 decoder renders at its
    own native resolution (typically 1024x1024, not 256x256) when resize=False
    — so the correspondence points below are derived from its actual size
    rather than a hardcoded 256.
    """
    w, h = original_img.size
    face_w, face_h = aged_face_img.size
    orig_np = np.array(original_img.convert("RGB"), dtype=np.float32)
    face_np = np.array(aged_face_img.convert("RGB"), dtype=np.float32)

    # (0,0)->TL, (0,face_h)->BL, (face_w,0)->TR of the aligned crop, mapped to
    # the same 3 corners in original-image space (quad_orig is a parallelogram,
    # so 3 correspondences fully determine the affine map).
    src = np.float32([[0, 0], [0, face_h], [face_w, 0]])
    dst = np.float32([quad_orig[0], quad_orig[1], quad_orig[3]])
    M = cv2.getAffineTransform(src, dst)

    # Ellipse/feather proportions tuned against a 256x256 reference; scaled to
    # whatever resolution the decoder actually produced.
    mask = np.zeros((face_h, face_w), dtype=np.float32)
    cx, cy = face_w / 2.0, face_h / 2.0
    ax, ay = face_w * (108.0 / 256.0), face_h * (118.0 / 256.0)
    cv2.ellipse(mask, (int(round(cx)), int(round(cy))), (int(round(ax)), int(round(ay))), 0, 0, 360, 1.0, -1)
    sigma = 18.0 * (face_w / 256.0)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma)

    warped_face = cv2.warpAffine(face_np, M, (w, h), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    warped_mask = cv2.warpAffine(mask, M, (w, h), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    warped_mask = warped_mask[..., None]

    composited = orig_np * (1 - warped_mask) + warped_face * warped_mask
    composited = np.clip(np.rint(composited), 0, 255).astype(np.uint8)
    return Image.fromarray(composited, "RGB")


class SAMWrapper:
    def __init__(self, model_path="SAM/pretrained_models/sam_ffhq_aging.pt",
                 predictor_path="SAM/shape_predictor_68_face_landmarks.dat"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading SAM model on {self.device}...")

        # Load Predictor
        if not os.path.exists(predictor_path):
            raise FileNotFoundError(f"Dlib shape predictor not found at {predictor_path}")
        self.predictor = dlib.shape_predictor(predictor_path)

        # Load Checkpoint
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"SAM model checkpoint not found at {model_path}")

        ckpt = torch.load(model_path, map_location="cpu")
        opts = ckpt['opts']
        opts['checkpoint_path'] = model_path
        opts['device'] = self.device
        opts = Namespace(**opts)

        self.net = pSp(opts)
        self.net.eval()
        self.net.to(self.device)
        print("SAM model loaded successfully!")

        self.img_transforms = transforms.Compose([
            transforms.Resize((256, 256)),
            transforms.ToTensor(),
            transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
        ])

    def process_image(self, image, target_age):
        """
        Age-progress the face in `image` to target_age, then composite the
        aged face back onto the ORIGINAL full-resolution photo so everything
        outside the face/head region (background, framing, clothing, scale)
        stays pixel-identical to the input. Never returns a fully synthetic
        whole-image result.

        image: PIL Image or filesystem path.
        target_age: int

        Returns (result_img: PIL.Image, meta: dict). meta["face_detected"] is
        False when no face could be aligned — in that case result_img is the
        original image, unchanged.
        """
        is_temp = False
        if isinstance(image, Image.Image):
            original_image = image.convert("RGB")
            file_path = os.path.join(SCRIPT_DIR, f"temp_align_input_{uuid.uuid4().hex[:8]}.jpg")
            original_image.save(file_path)
            is_temp = True
        else:
            file_path = image
            original_image = Image.open(file_path).convert("RGB")

        try:
            try:
                aligned_image, quad_orig = _align_face_with_quad(file_path, self.predictor)
            except FaceNotFoundError:
                return original_image.copy(), {"face_detected": False}

            aligned_image = aligned_image.resize((256, 256))

            input_image = self.img_transforms(aligned_image)

            age_transformer = AgeTransformer(target_age=target_age)
            input_image_with_age = age_transformer(input_image)
            input_image_with_age = input_image_with_age.unsqueeze(0).to(self.device)

            with torch.no_grad():
                result_batch = self.net(input_image_with_age, randomize_noise=False, resize=False)

            aged_256 = tensor2im(result_batch[0])

            composited = _composite_aged_face(original_image, aged_256, quad_orig)
            return composited, {"face_detected": True}
        finally:
            if is_temp and os.path.exists(file_path):
                os.remove(file_path)


# Singleton instance
_sam_instance = None

def get_sam_wrapper():
    global _sam_instance
    if _sam_instance is None:
        _sam_instance = SAMWrapper()
    return _sam_instance
