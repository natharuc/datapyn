"""Frozen sidecar entrypoint; divert multiprocessing children before app imports."""

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    from datapyn_runtime.__main__ import main

    main()
