import matplotlib.pyplot as plt

def plot_iou_histogram(tile_ious: dict, out_png: str):
    vals = list(tile_ious.values())
    plt.hist(vals, bins=20)
    plt.xlabel("Tile IoU (manual vs auto)")
    plt.ylabel("Number of tiles")
    plt.title("Tile Matching Confidence (IoU)")
    plt.savefig(out_png)
    plt.close()
