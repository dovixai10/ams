"""
Face recognition utility functions for employee verification
"""
import sys

# Keep these imports independent.  In particular, a missing face_recognition
# package must not make Pillow unavailable: the latter is needed to read the
# uploaded image and give the user a meaningful dependency error.
try:
    import numpy as np
except ImportError as e:
    print(f"⚠️  NumPy is unavailable: {e}", file=sys.stderr)
    np = None

try:
    import cv2
except ImportError as e:
    print(f"⚠️  OpenCV is unavailable: {e}", file=sys.stderr)
    cv2 = None

try:
    import face_recognition
    import dlib

    print(
        f"✅ Face recognition loaded. "
        f"dlib version: {dlib.__version__}",
        file=sys.stderr
    )

    FACE_RECOGNITION_IMPORT_ERROR = None

except Exception as e:
    import traceback

    print(
        f"❌ Face recognition import failed: "
        f"{type(e).__name__}: {e}",
        file=sys.stderr
    )

    traceback.print_exc(file=sys.stderr)

    face_recognition = None
    FACE_RECOGNITION_IMPORT_ERROR = (
        f"{type(e).__name__}: {e}"
    )

try:
    from PIL import Image
except ImportError as e:
    print(f"⚠️  Pillow is unavailable: {e}", file=sys.stderr)
    Image = None

import io
from django.conf import settings
from .models import Employee


def _face_recognition_available():
    """Return whether all libraries required for face encoding are installed."""
    return face_recognition is not None and np is not None and Image is not None


def extract_face_encoding(image_path):
    """
    Extract face encoding from an image file path
    
    Args:
        image_path: Path to the image file
        
    Returns:
        numpy array of face encoding or None if no face found
    """
    try:
        # Load image
        image = face_recognition.load_image_file(image_path)
        
        # Get face encodings
        face_encodings = face_recognition.face_encodings(image)
        
        if face_encodings:
            # Return the first face encoding found
            return face_encodings[0]
        else:
            return None
            
    except Exception as e:
        print(f"Error extracting face encoding: {str(e)}")
        return None


def extract_face_encoding_from_file(uploaded_file):
    """
    Extract face encoding from an uploaded file object
    
    Args:
        uploaded_file: Django UploadedFile object
        
    Returns:
        numpy array of face encoding or None if no face found
    """
    try:
        # Read the uploaded file
        image = Image.open(uploaded_file)
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Convert PIL Image to numpy array
        image_array = np.array(image)
        
        # Get face encodings
        face_encodings = face_recognition.face_encodings(image_array)
        
        if face_encodings:
            return face_encodings[0]
        else:
            return None
            
    except Exception as e:
        print(f"Error extracting face encoding from file: {str(e)}")
        return None


def extract_face_encoding_from_file_bytes(image_bytes):
    """
    Extract face encoding from raw image bytes (base64 decoded or file content)
    
    Args:
        image_bytes: Raw bytes of the image file
        
    Returns:
        numpy array of face encoding or None if no face found or multiple faces detected
    """
    if not _face_recognition_available():
        print("[ERROR] Face registration is unavailable: install face-recognition and its dependencies.")
        return None

    try:
        # Convert bytes to PIL Image
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Convert PIL Image to numpy array
        image_array = np.array(image)
        
        print(f"[DEBUG] Image shape: {image_array.shape}, dtype: {image_array.dtype}")
        
        # Detect faces first.  A webcam frame often contains a relatively
        # small face within a 720p image, so retry with extra upsampling when
        # the normal HOG pass finds none.
        face_locations = face_recognition.face_locations(
            image_array,
            number_of_times_to_upsample=1,
            model="hog",
        )

        if not face_locations:
            print("[DEBUG] Retrying face detection with higher sensitivity")
            face_locations = face_recognition.face_locations(
                image_array,
                number_of_times_to_upsample=2,
                model="hog",
            )
        
        print(f"[DEBUG] Faces detected: {len(face_locations)}")
        
        if len(face_locations) == 0:
            # No face detected
            print("[DEBUG] No face detected in image")
            return None
        elif len(face_locations) > 1:
            # Multiple faces detected - use the largest/most prominent one
            print(f"[DEBUG] Multiple faces detected: {len(face_locations)}, using the largest")
            # Find the largest face (by area)
            largest_idx = 0
            largest_area = 0
            for idx, (top, right, bottom, left) in enumerate(face_locations):
                area = (right - left) * (bottom - top)
                if area > largest_area:
                    largest_area = area
                    largest_idx = idx
            face_locations = [face_locations[largest_idx]]
        
        # Get face encodings
        face_encodings = face_recognition.face_encodings(image_array, face_locations)
        
        print(f"[DEBUG] Face encodings extracted: {len(face_encodings)}")
        
        if face_encodings:
            encoding = face_encodings[0]
            print(f"[DEBUG] Encoding shape: {encoding.shape}, dtype: {encoding.dtype}")
            print(f"[DEBUG] Encoding sample values: {encoding[:5]}")
            return encoding
        else:
            print("[DEBUG] No encodings extracted")
            return None
            
    except Exception as e:
        import traceback
        print(f"[ERROR] Error extracting face encoding from bytes: {str(e)}")
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        return None


def compare_faces(known_encoding, unknown_encoding, tolerance=0.6):
    """
    Compare two face encodings
    
    Args:
        known_encoding: numpy array of the known face encoding
        unknown_encoding: numpy array of the unknown face encoding
        tolerance: How much distance between faces to consider a match (default 0.6)
        
    Returns:
        dict with 'match' (bool), 'distance' (float), and 'confidence' (float percentage)
    """
    try:
        if known_encoding is None or unknown_encoding is None:
            print(f"[DEBUG] Encoding is None - known: {known_encoding is None}, unknown: {unknown_encoding is None}")
            return {
                'match': False,
                'distance': 1.0,
                'confidence': 0.0
            }
        
        # Check if encodings are all zeros (placeholder)
        known_is_zero = np.allclose(known_encoding, 0.0)
        unknown_is_zero = np.allclose(unknown_encoding, 0.0)
        print(f"[DEBUG] Known encoding all zeros: {known_is_zero}, Unknown all zeros: {unknown_is_zero}")
        
        if known_is_zero or unknown_is_zero:
            print("[DEBUG] WARNING: One or both encodings are all zeros (placeholder)")
        
        # Calculate face distance
        face_distance = face_recognition.face_distance([known_encoding], unknown_encoding)[0]
        
        # Check if faces match
        matches = face_recognition.compare_faces([known_encoding], unknown_encoding, tolerance=tolerance)
        
        # Calculate confidence (inverse of distance, as percentage)
        confidence = max(0, (1 - face_distance) * 100)
        
        print(f"[DEBUG] Face comparison - Distance: {face_distance:.4f}, Tolerance: {tolerance}, Match: {matches[0]}, Confidence: {confidence:.1f}%")
        
        return {
            'match': bool(matches[0]),
            'distance': float(face_distance),
            'confidence': float(confidence)
        }
        
    except Exception as e:
        import traceback
        print(f"[ERROR] Error comparing faces: {str(e)}")
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        return {
            'match': False,
            'distance': 1.0,
            'confidence': 0.0
        }


def get_match_tolerance(default=0.6):
    """Read face match tolerance from settings if provided"""
    return getattr(settings, 'FACE_MATCH_TOLERANCE', default)


def get_strict_match_tolerance(default=0.45):
    """Return a stricter tolerance for one-to-one verifications."""
    return getattr(settings, 'FACE_STRICT_MATCH_TOLERANCE', default)


def is_encoding_unique(new_encoding, exclude_employee_id=None, tolerance=None):
    """
    Check that a face encoding is unique across all employees.

    Args:
        new_encoding: numpy array for new face
        exclude_employee_id: optional employee id to exclude from comparison
        tolerance: optional override tolerance

    Returns:
        (is_unique: bool, conflict_employee: Employee | None, distance: float | None)
    """
    if new_encoding is None:
        return True, None, None

    tol = tolerance if tolerance is not None else get_match_tolerance()

    qs = (
        Employee.objects.exclude(face_encoding__isnull=True)
        .exclude(face_encoding="")
        .filter(face_registered=True)
    )
    if exclude_employee_id:
        qs = qs.exclude(pk=exclude_employee_id)

    for emp in qs:
        known = emp.get_face_encoding()
        if known is None:
            continue
        # Use face_distance to compute similarity
        distance = float(face_recognition.face_distance([known], new_encoding)[0])
        match = bool(face_recognition.compare_faces([known], new_encoding, tolerance=tol)[0])
        if match:
            return False, emp, distance

    return True, None, None


def find_best_face_match(unknown_encoding, employee_queryset, tolerance=None, uniqueness_margin=0.05):
    """Find the best matching employee for the provided encoding ensuring uniqueness."""

    if unknown_encoding is None:
        return None

    candidates = []
    encodings = []
    for employee in employee_queryset:
        encoding = employee.get_face_encoding()
        if encoding is None:
            continue
        candidates.append(employee)
        encodings.append(encoding)

    if not encodings:
        return None

    encodings_array = np.stack(encodings)
    distances = face_recognition.face_distance(encodings_array, unknown_encoding)

    best_index = int(np.argmin(distances))
    best_distance = float(distances[best_index])

    tol = tolerance if tolerance is not None else get_match_tolerance()
    if best_distance > tol:
        return None

    within_tol = [float(d) for d in distances if d <= tol]
    if len(within_tol) > 1:
        sorted_distances = sorted(within_tol)
        if sorted_distances[1] - sorted_distances[0] < uniqueness_margin:
            return None

    confidence = max(0.0, (1.0 - best_distance) * 100)

    return {
        'employee': candidates[best_index],
        'distance': best_distance,
        'confidence': confidence,
    }


def validate_face_image(image_path):
    """
    Validate that an image contains exactly one detectable face
    
    Args:
        image_path: Path to the image file
        
    Returns:
        dict with 'valid' (bool), 'face_count' (int), and 'message' (str)
    """
    try:
        # Load image
        image = face_recognition.load_image_file(image_path)
        
        # Detect faces
        face_locations = face_recognition.face_locations(image)
        face_count = len(face_locations)
        
        if face_count == 0:
            return {
                'valid': False,
                'face_count': 0,
                'message': 'No face detected in the image. Please upload a clear photo of your face.'
            }
        elif face_count > 1:
            return {
                'valid': False,
                'face_count': face_count,
                'message': f'Multiple faces detected ({face_count}). Please upload a photo with only one person.'
            }
        else:
            return {
                'valid': True,
                'face_count': 1,
                'message': 'Face detected successfully.'
            }
            
    except Exception as e:
        return {
            'valid': False,
            'face_count': 0,
            'message': f'Error validating image: {str(e)}'
        }


def process_and_store_face_encoding(employee, image_path):
    """
    Process an image and store the face encoding in the employee model
    
    Args:
        employee: Employee model instance
        image_path: Path to the image file
        
    Returns:
        dict with 'success' (bool) and 'message' (str)
    """
    try:
        # Validate the image
        validation = validate_face_image(image_path)
        
        if not validation['valid']:
            return {
                'success': False,
                'message': validation['message']
            }
        
        # Extract face encoding
        encoding = extract_face_encoding(image_path)
        
        if encoding is None:
            return {
                'success': False,
                'message': 'Failed to extract face encoding from the image.'
            }
        
        # Ensure uniqueness across all employees
        is_unique, conflict_emp, distance = is_encoding_unique(encoding, exclude_employee_id=employee.pk)
        if not is_unique:
            return {
                'success': False,
                'message': f'This face appears to match an existing employee ("{conflict_emp.full_name}"). Please use a unique face image.'
            }

        # Store the encoding
        employee.set_face_encoding(encoding)
        employee.save()

        return {
            'success': True,
            'message': 'Face registered successfully!'
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Error processing face: {str(e)}'
        }
