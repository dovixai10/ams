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
    """Legacy/loose tolerance - kept only for backward compatibility with
    any external caller that explicitly wants it. Actual match decisions
    everywhere in this app (web, mobile, and the open kiosk) now go
    through get_strict_match_tolerance() instead, so 1:1 verification and
    1:N identification use the same, single, tunable threshold rather than
    three different hardcoded numbers drifting apart."""
    return getattr(settings, 'FACE_MATCH_TOLERANCE', default)


def get_strict_match_tolerance(default=0.45):
    """Tolerance for 1:1 verification only - web/mobile check-in/out,
    comparing the live photo against the logged-in employee's own single
    encoding. Deliberately tight, since it's a one-to-one confirmation
    and the risk of a false accept there is different from the kiosk's."""
    return getattr(settings, 'FACE_STRICT_MATCH_TOLERANCE', default)


def get_kiosk_match_tolerance(default=0.45):
    """Tolerance for the open, unauthenticated kiosk's 1:N search
    (find_best_face_match, identifying who's in front of the camera out
    of the whole office roster).

    This was loosened to 0.6 at one point to fight false *rejects* (a
    registered employee's messy-hair day not matching their one
    enrollment photo) - and that was a mistake: it let a person who
    isn't even registered at this office get matched to a real employee
    ("Indrajeet"). find_best_face_match's uniqueness-margin check only
    protects against *ambiguity between two registered candidates* - it
    does nothing when a total stranger's face simply happens to fall
    within a loose tolerance of one specific employee, which is exactly
    what a 6-candidate office-wide search risks doing at 0.6. Back to the
    same strict number as 1:1 verification: handing attendance to the
    wrong identity (or a non-employee entirely) is a materially worse
    failure than occasionally asking a legitimate employee to re-scan.
    The real fix for the false-reject problem is better enrollment
    (multiple reference photos - see the earlier discussion), not a
    looser tolerance on the highest-stakes, unauthenticated endpoint."""
    return getattr(settings, 'FACE_KIOSK_MATCH_TOLERANCE', default)


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


# ---------------------------------------------------------------------------
# Liveness (blink) detection for the open, unauthenticated kiosk endpoint.
#
# The kiosk has no login to anchor identity to, so a static printed/screen
# photo held up to the camera would otherwise match just as well as a real
# person. Requiring a real blink across a short burst of frames is a cheap,
# camera-only liveness signal: a photo can't blink.
# ---------------------------------------------------------------------------

def _eye_aspect_ratio(eye_points):
    """Standard Eye Aspect Ratio from the 6 eye-contour points dlib's
    68-point model returns, in its fixed order: p1 (outer corner), p2, p3
    (upper lid), p4 (inner corner), p5, p6 (lower lid).

        EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)

    This stays roughly constant for an open eye regardless of face size/
    distance from the camera (it's a ratio, not an absolute measurement),
    and drops sharply for the few frames an eye is closed - that dip is
    what a blink looks like numerically.
    """
    import math

    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    if not eye_points or len(eye_points) < 6:
        return None
    p1, p2, p3, p4, p5, p6 = eye_points[:6]
    horizontal = dist(p1, p4)
    if horizontal == 0:
        return None
    vertical = dist(p2, p6) + dist(p3, p5)
    return vertical / (2.0 * horizontal)


def get_frame_ear(image_array, face_location):
    """Average eye-aspect-ratio for one already-located face in one frame,
    or None if landmarks couldn't be read for it."""
    if not _face_recognition_available() or face_location is None:
        return None
    try:
        landmarks_list = face_recognition.face_landmarks(image_array, face_locations=[face_location])
    except Exception:
        return None
    if not landmarks_list:
        return None
    landmarks = landmarks_list[0]
    ears = [
        e for e in (
            _eye_aspect_ratio(landmarks.get('left_eye')),
            _eye_aspect_ratio(landmarks.get('right_eye')),
        )
        if e is not None
    ]
    if not ears:
        return None
    return sum(ears) / len(ears)


def detect_blink_in_sequence(ear_sequence, dip_ratio=0.75, min_frames=4):
    """Given the EAR values for a short burst of consecutive frames (in
    capture order, None for any frame no face/eyes were readable in),
    decide whether a genuine blink happened.

    A blink is a dip: EAR drops well below the "eyes open" baseline for
    one or more middle frames, then recovers. We compare the sequence's
    minimum against the baseline (the higher of the first and last
    frame's EAR, since a real blink is bracketed by open-eye frames on
    both sides) using a *relative* drop (25% by default) rather than a
    fixed absolute cutoff - eye shape and camera angle vary enough
    between people that an absolute threshold like "EAR < 0.2" misses or
    false-fires for a lot of real faces.

    Returns (blink_detected, best_frame_index). best_frame_index points at
    the highest-EAR frame at or after the dip (eyes freshly reopened -
    sharper and more natural than a mid-blink frame), which is the frame
    the caller should extract the face encoding from. Returns
    best_frame_index=None only if no frame had a readable face at all.
    """
    valid = [(i, ear) for i, ear in enumerate(ear_sequence) if ear is not None]
    if len(valid) < min_frames:
        return False, (valid[-1][0] if valid else None)

    indices = [i for i, _ in valid]
    ears = [e for _, e in valid]

    baseline = max(ears[0], ears[-1])
    min_ear = min(ears)
    dip_index = ears.index(min_ear)

    blink_detected = baseline > 0 and min_ear <= baseline * dip_ratio

    post_dip = [(idx, ear) for idx, ear in zip(indices, ears) if idx >= indices[dip_index]]
    best_index = max(post_dip, key=lambda pair: pair[1])[0] if post_dip else indices[-1]

    return blink_detected, best_index
