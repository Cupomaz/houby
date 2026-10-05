import os
from PIL import Image
import config  # Reusing config from your project structure


def generate_coverage_map(
    img_dir: str = "img",
    output_path: str = "coverage_map.png",
    grid_size: int = 512,
):
    # Create 512x512 image in 8-bit grayscale ('L' mode), filled with 255 (white)
    img = Image.new("L", (grid_size, grid_size), color=255)
    pixels = img.load()

    if not os.path.exists(img_dir):
        print(f"Directory '{img_dir}' not found.")
        return

    # Load all existing filenames into a set for fast O(1) lookups
    existing_files = set(os.listdir(img_dir))

    # Map tiles onto the image grid
    for row in range(grid_size):
        for col in range(grid_size):
            filename = f"{row}x{col}.png"
            if filename in existing_files:
                # Pillow coordinates are (x, y) -> (column, row)
                # (0, 0) is top-left
                pixels[col, row] = 0  # 0 = Black

    # Save output map
    img.save(output_path)

    print(f"Coverage map saved to: {output_path}")



if __name__ == "__main__":
    generate_coverage_map(
        img_dir=getattr(config, "OUTPUT_DIR", "img"),
        output_path="coverage_map.png",
        grid_size=512,
    )