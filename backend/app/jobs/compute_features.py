"""
(Re)calculate audio measurements for every event that has a stored clip.

Run after changing app/services/acoustic_features.py (bump METHOD first, so the old
results stay for comparison):
    docker exec haman-api python -m app.jobs.compute_features            # missing only
    docker exec haman-api python -m app.jobs.compute_features --all      # recompute all
"""
import sys

from sqlalchemy import select

from ..clips_db import ClipsSessionLocal, clips_engine
from ..database import SessionLocal
from ..models import CoughEvent, CoughEventFeatures
from ..services import acoustic_features, clip_store

BATCH = 200


def main(recompute_all: bool = False) -> None:
    if clips_engine is None:
        print("clips database not configured; nothing to do")
        return
    done = skipped = 0
    with SessionLocal() as db, ClipsSessionLocal() as clips_db:
        q = select(CoughEvent).where(CoughEvent.clip_anon_id.is_not(None)).order_by(CoughEvent.id)
        if not recompute_all:
            have = select(CoughEventFeatures.event_id).where(
                CoughEventFeatures.method == acoustic_features.METHOD)
            q = q.where(CoughEvent.id.not_in(have))
        for event in db.scalars(q).yield_per(BATCH):
            wav = clip_store.read_clip(clips_db, event.clip_anon_id)
            if wav is not None and clip_store.save_features(db, event, wav):
                done += 1
            else:
                skipped += 1
            if (done + skipped) % BATCH == 0:
                db.commit()
        db.commit()
    print(f"{acoustic_features.METHOD}: measured {done} events, skipped {skipped}")


if __name__ == "__main__":
    main(recompute_all="--all" in sys.argv)
