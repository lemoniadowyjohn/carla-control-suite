from ultimate_pipeline.entrypoints import ENTRYPOINTS

def main():
    for k, e in ENTRYPOINTS.items():
        print(f"{k:12s} -> {e.module:60s} | {e.description}")

if __name__ == "__main__":
    main()
