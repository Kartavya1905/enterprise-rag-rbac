"""
PACKAGE: scripts - command-line tools.

Dev only (left out of the Docker image, see .dockerignore):
    generate_dataset.py   builds the synthetic company documents   (Phase 2)
    run_evals.py          red-team + quality evaluations            (Phase 11)
    dataset/, evals/      code used by the two scripts above

Also in the Docker image (run with `docker compose exec api python -m scripts.<name>`):
    seed_users.py         creates login accounts for the personas   (Phase 3)
    ingest_documents.py   parse + chunk + register documents        (Phase 4)
    index_chunks.py       embed + index chunks into Qdrant          (Phase 5)
    bootstrap.py          the three steps above in one command      (Phase 12)
    smoke_test.py         checks a running API is up AND secure     (Phase 12)
    demo.py               side-by-side answers for different users  (Phase 12)
    create_user.py        adds one real account (production)        (Phase 12)
"""
