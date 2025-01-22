from typing import List 
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel
import cv2
import numpy as np
from classifiers import predict_avalanche_type, predict_spam
from inference import get_sam_predictor 
import base64
import io
from sam import select_point

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global states
predictor = None
# IDEA: Just save the original image and whenever we show the image
# we apply the 'counter' number of transformations to it
original_image = None
# keeps track of how many masks there are in the image
counter = 0

class Point(BaseModel):
    x: int
    y: int

def encode_image(image_array: np.ndarray) -> str:
    """Convert numpy array to base64 string."""
    success, encoded_image = cv2.imencode('.png', image_array)
    if success:
        return base64.b64encode(encoded_image.tobytes()).decode('utf-8')
    return ""

def decode_image(base64_string: str) -> np.ndarray:
    """Convert base64 string to numpy array."""
    img_data = base64.b64decode(base64_string)
    img_array = np.frombuffer(img_data, np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)

def overlay_mask(image: np.ndarray, mask: np.ndarray, alpha: float = 0.5):
    """Overlay mask on image with transparency."""
    overlay = image.copy()
    if mask.any():
        overlay[mask > 0] = [255, 0, 0]  # Red overlay for mask
    return cv2.addWeighted(overlay, alpha, image, 1 - alpha, 0)

@app.post("/spamcheck")
async def spam_classify_image(file: UploadFile = File(...)):
    try:
        # Ensure the uploaded file is an image
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload an image.")

        # Read image file
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data)).convert("RGB")

        # Classify image
        predicted_class = predict_spam(image)
        # If image is not spam we save it and add it to predictor
        if predicted_class != 0:
            global predictor, original_image
            original_image=image
            predictor = get_sam_predictor(device='cpu', image=original_image)

        # return true or false
        return JSONResponse(content={"spam": predicted_class == 0})

    except HTTPException as e:
        return JSONResponse(content={"error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/checkavalanchetype")
async def classify_avalanche_type(file: UploadFile = File(...)):
    try:
        # Read image file
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        
        # Classify image
        predicted_class = predict_avalanche_type(image)
        

        # return true or false
        return JSONResponse(content={"avalanche_type": predicted_class})

    except HTTPException as e:
        return JSONResponse(content={"error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    # We save the image in a global variable
    # we set the image to SAM model predictor.set_image(img)
    global original_image
    
    # Read and process image
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    current_image = img.copy()
    display_image = img.copy()
    predictor.set_image(current_image)
    
    return {"image": encode_image(display_image)}

@app.post("/add_point")
async def add_point(point: Point):
    """
        When user clicks on image we do segmentation on image 
        and return the image.
    """
    global predictor, original_image, counter
    counter += 1

    # segment point
    img = select_point(
        predictor=predictor,
        original_img=original_image,
        display_img=display_image,
        point=point,
        counter=counter,
    )
    
    return {
        "image": encode_image(display_image),
    }

@app.post("/undo")
async def undo():
    global display_image, masks, points
    
    if points:
        # Remove last point and mask
        points.pop()
        if masks:
            masks.pop()
        
        # Recreate display image from scratch
        display_image = current_image.copy()
        
        # Redraw all masks
        for mask in masks:
            display_image = overlay_mask(display_image, mask)
        
        # Redraw all points
        for px, py in points:
            cv2.drawMarker(display_image, (px, py), (255, 0, 0), 
                          markerType=1, markerSize=5, thickness=2)
    
    return {"image": encode_image(display_image)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)