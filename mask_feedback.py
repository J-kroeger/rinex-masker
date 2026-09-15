# -*- coding: utf-8 -*-
r"""
Keep the mask corrections a user makes, so the segmentation can learn from them.

When someone corrects an automatic mask by hand, that correction is exactly the
signal a segmentation model needs in order to improve, so it is worth keeping
rather than discarding.

What that means in practice, and the reason this module is so small:

  * the interesting thing is not the corrected profile, it is the **difference**
    between what the automatic step produced and what the person moved it to.
    That difference is the label, so both profiles are stored side by side;
  * the image is stored as the **original file**, copied byte for byte, not
    re-encoded from the array the program happens to hold. A training run has to
    see exactly what the segmentation saw;
  * everything stays **local**, in `mask_feedback\` next to the program. Nothing
    is uploaded, and nothing is sent anywhere. The folder is collected by hand
    and passed on. Retraining happens elsewhere; this module only collects.

The data accumulates slowly, which is exactly why the pipeline is built now
and left to fill.

Nothing here may interrupt the user: every public function catches its own
errors and returns None rather than raising into the GUI. A failure to store a
training sample is not a reason to lose someone's mask.
"""

import json
import os
import shutil
import sys
from datetime import datetime

FORMAT = "pcc-mask-feedback-v1"
FOLDER_NAME = "mask_feedback"

# Below this, a point has not really been moved in azimuth at all.
_AZ_TOLERANCE_DEG = 0.05

# Below this, an elevation change is rounding, not a correction.
_EL_TOLERANCE_DEG = 0.05

# How far a dragged point may travel in azimuth and still be recognised as the
# same point rather than as one deletion plus one insertion. A drag moves a
# point across the plane, so it lands between the azimuths of the grid it
# started on; the spacing of that grid is therefore the scale of the window.
# Kept just under one full spacing: at exactly one, a point sits the same
# distance from its own slot and from its neighbour's and the attribution is a
# coin toss, so a point that jumps a whole cell is read as a deletion plus an
# insertion instead. max_az_shift_deg reports how far the matched ones moved.
_MATCH_WINDOW_FACTOR = 0.9
_DEFAULT_AZ_SPACING_DEG = 5.0

_README = """RINEX-Masker: mask correction feedback
======================================

This folder collects the corrections you make to an automatically generated
obstruction mask, so that the sky segmentation behind "Auto-Mask from Image"
can be improved.

One sub-folder is written each time you change a generated profile in
"Fine-Tune Points" and apply it. It contains:

  image.<ext>      the image the profile was extracted from, copied unchanged
  photo.<ext>      the original photograph, if you corrected on one instead
  sample.json      the automatic profile, your corrected profile, and the
                   camera geometry needed to interpret them

Nothing here is uploaded, and nothing is sent anywhere. The files stay on this
machine until you pass them on yourself. If you would rather not keep them,
delete the folder; the program writes a new one only when you correct a mask
again, and it never reads what is already here.

If you are willing to share them, send the folder to the address in the
Contact dialog. Corrections from real sites are the most useful training data
there is, because they are exactly the cases the automatic step got wrong.

Institut für Erdmessung (IfE), Leibniz Universität Hannover.
"""


def app_dir():
    """The folder the program runs from, frozen build or source checkout."""
    try:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def feedback_dir(base=None, create=True):
    """`mask_feedback\\` next to the program, created on first use."""
    path = os.path.join(base or app_dir(), FOLDER_NAME)
    if create:
        os.makedirs(path, exist_ok=True)
        readme = os.path.join(path, "README.txt")
        if not os.path.exists(readme):
            with open(readme, "w", encoding="utf-8") as fh:
                fh.write(_README)
    return path


def _as_pairs(profile):
    """[(az, el), ...] as plain floats, tolerating tuples, lists or None."""
    out = []
    for item in profile or []:
        try:
            az, el = item[0], item[1]
            out.append((float(az), float(el)))
        except Exception:
            continue
    return out


def _az_delta(a, b):
    """Signed smallest angle from b to a, in degrees, wrapping at 360."""
    return (a - b + 180.0) % 360.0 - 180.0


def _median_az_spacing(pairs):
    """Spacing of the grid a profile sits on, used as the matching window."""
    az = sorted(p[0] for p in pairs)
    gaps = sorted(b - a for a, b in zip(az, az[1:]) if b > a)
    if not gaps:
        return _DEFAULT_AZ_SPACING_DEG
    return gaps[len(gaps) // 2] or _DEFAULT_AZ_SPACING_DEG


def compare(automatic, corrected):
    """
    What the person changed, which is the part worth learning from.

    Each corrected point is matched to the NEAREST automatic point in azimuth,
    not to one carrying the same azimuth. Dragging a point moves it across the
    plane, so its azimuth shifts by whole degrees off the 5 degree grid the
    automatic step produced. Matching on equality therefore read every drag as
    one deletion plus one insertion and left "moved", "max_change_deg",
    "raised" and "lowered" at zero, which are exactly the numbers the label is
    for. Matching is still not by index, so adding or removing a point does not
    make everything after it look moved.
    """
    auto = _as_pairs(automatic)
    corr = _as_pairs(corrected)
    window = _median_az_spacing(auto) * _MATCH_WINDOW_FACTOR

    # Nearest pairs claim each other first, so a point the user really added
    # cannot steal the partner of one that was only moved.
    candidates = sorted(
        (abs(_az_delta(caz, aaz)), ci, ai)
        for ci, (caz, _) in enumerate(corr)
        for ai, (aaz, _) in enumerate(auto)
        if abs(_az_delta(caz, aaz)) <= window)

    partner, taken = {}, set()
    for _, ci, ai in candidates:
        if ci in partner or ai in taken:
            continue
        partner[ci] = ai
        taken.add(ai)

    moved, deltas, az_shifts = 0, [], []
    for ci, (caz, cel) in enumerate(corr):
        ai = partner.get(ci)
        if ai is None:
            continue
        aaz, ael = auto[ai]
        d_el = cel - ael
        d_az = _az_delta(caz, aaz)
        if abs(d_el) > _EL_TOLERANCE_DEG or abs(d_az) > _AZ_TOLERANCE_DEG:
            moved += 1
            deltas.append(d_el)
            az_shifts.append(d_az)

    added = len(corr) - len(partner)
    removed = len(auto) - len(taken)

    return {
        "points_automatic": len(auto),
        "points_corrected": len(corr),
        "moved": moved,
        "added": added,
        "removed": removed,
        "changed": moved + added + removed,
        "max_change_deg": round(max((abs(d) for d in deltas), default=0.0), 2),
        "mean_abs_change_deg": round(
            sum(abs(d) for d in deltas) / len(deltas), 2) if deltas else 0.0,
        "max_az_shift_deg": round(
            max((abs(d) for d in az_shifts), default=0.0), 2),
        "raised": sum(1 for d in deltas if d > _EL_TOLERANCE_DEG),
        "lowered": sum(1 for d in deltas if d < -_EL_TOLERANCE_DEG),
        "match_window_deg": round(window, 2),
    }


def _stamp_name(source_path, when):
    stem = os.path.splitext(os.path.basename(source_path or "profile"))[0]
    stem = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)[:40]
    return "%s_%s" % (when.strftime("%Y-%m-%d_%H%M%S"), stem or "profile")


def _copy_image(src, dest_dir, stem):
    """Copy the file unchanged. Returns the stored name, or None."""
    if not src or not os.path.isfile(src):
        return None
    ext = os.path.splitext(src)[1].lower() or ".png"
    name = stem + ext
    try:
        shutil.copy2(src, os.path.join(dest_dir, name))
        return name
    except Exception as exc:
        print("[WARNING] Could not copy %s into the feedback folder: %s"
              % (os.path.basename(src), exc))
        return None


def save_sample(source_path, corrected, automatic=None, edited_from=None,
                photo_path=None, geometry=None, extraction=None,
                source_info=None, program=None, base=None):
    """
    Store one correction. Returns the folder that was written, or None.

    None means "nothing worth keeping" as often as it means "it failed": a
    profile that was not changed, or one with no image behind it, teaches the
    segmentation nothing.
    """
    try:
        auto = _as_pairs(automatic if automatic is not None else edited_from)
        corr = _as_pairs(corrected)
        if not corr or not auto:
            return None
        if not source_path or not os.path.isfile(source_path):
            return None

        diff = compare(auto, corr)
        if diff["changed"] == 0:
            return None

        # Two different questions, and only asking the first one stored the
        # same correction twice: a user who reopens the editor and changes
        # nothing still ends up with a profile that differs from the automatic
        # one. What is stored is the correction as a whole, but what decides
        # whether to store it is whether THIS visit to the editor changed
        # anything.
        started = _as_pairs(edited_from)
        if started and compare(started, corr)["changed"] == 0:
            return None

        when = datetime.now()
        root = feedback_dir(base)
        folder = os.path.join(root, _stamp_name(source_path, when))
        suffix = 1
        while os.path.exists(folder):
            suffix += 1
            folder = os.path.join(root, "%s_%d"
                                  % (_stamp_name(source_path, when), suffix))
        os.makedirs(folder)

        image_name = _copy_image(source_path, folder, "image")
        photo_name = None
        if photo_path and os.path.abspath(photo_path) != os.path.abspath(source_path):
            photo_name = _copy_image(photo_path, folder, "photo")

        sample = {
            "format": FORMAT,
            "created": when.strftime("%Y-%m-%dT%H:%M:%S"),
            "program": program or {"name": "RINEX-Masker"},
            "source": dict(source_info or {},
                           image_file=image_name,
                           original_name=os.path.basename(source_path),
                           photo_file=photo_name,
                           photo_original_name=(os.path.basename(photo_path)
                                                if photo_name else None)),
            "geometry": geometry or {},
            "extraction": extraction or {},
            "profiles": {
                "automatic": [[round(az, 3), round(el, 3)] for az, el in auto],
                "corrected": [[round(az, 3), round(el, 3)] for az, el in corr],
            },
            "difference": diff,
        }
        # Only worth storing when the editor did not start from the automatic
        # profile, otherwise it is a third identical copy.
        if started and started != auto:
            sample["profiles"]["edited_from"] = [
                [round(az, 3), round(el, 3)] for az, el in started]

        with open(os.path.join(folder, "sample.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(sample, fh, indent=2)

        print("[OK] Stored a mask correction for training in %s" % folder)
        return folder
    except Exception as exc:
        print("[WARNING] Could not store the mask correction: %s" % exc)
        return None


def count_samples(base=None):
    """How many corrections have been collected so far."""
    try:
        root = feedback_dir(base, create=False)
        if not os.path.isdir(root):
            return 0
        return sum(1 for name in os.listdir(root)
                   if os.path.isfile(os.path.join(root, name, "sample.json")))
    except Exception:
        return 0
