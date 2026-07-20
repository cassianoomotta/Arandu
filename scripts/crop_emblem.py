import os
from PIL import Image, ImageChops

def process_emblem(input_path, output_path, output_full_logo_path=None):
    if not os.path.exists(input_path):
        print(f"File not found: {input_path}")
        return

    img = Image.open(input_path).convert("RGBA")
    width, height = img.size
    print(f"Original image size: {width}x{height}")

    # Create new image for transparent output
    data = img.getdata()
    new_data = []

    for item in data:
        r, g, b, a = item
        # Luminance / brightness approximation
        brightness = max(r, g, b)
        
        # Black background thresholding with smooth alpha transition
        if brightness < 12:
            new_data.append((0, 0, 0, 0))
        elif brightness < 45:
            # Smooth transition factor for anti-aliasing edge
            alpha = int(((brightness - 12) / (45 - 12)) * 255)
            # Boost color slightly so black doesn't contaminate transparent edge
            boost_r = min(255, int(r * 1.3))
            boost_g = min(255, int(g * 1.3))
            boost_b = min(255, int(b * 1.3))
            new_data.append((boost_r, boost_g, boost_b, alpha))
        else:
            new_data.append((r, g, b, 255))

    transparent_img = Image.new("RGBA", img.size)
    transparent_img.putdata(new_data)

    # Get bounding box of alpha > 0 pixels
    bbox = transparent_img.getbbox()
    print(f"Bounding box: {bbox}")

    if bbox:
        left, upper, right, lower = bbox
        cropped_img = transparent_img.crop(bbox)
        crop_w = right - left
        crop_h = lower - upper
        print(f"Cropped emblem dimensions: {crop_w}x{crop_h}")

        # Create a square canvas with symmetric alignment and padding
        max_dim = max(crop_w, crop_h)
        padding = int(max_dim * 0.1) # 10% padding
        canvas_size = max_dim + (padding * 2)

        # Ensure canvas is even size for exact integer centering
        if canvas_size % 2 != 0:
            canvas_size += 1

        square_img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        offset_x = (canvas_size - crop_w) // 2
        offset_y = (canvas_size - crop_h) // 2

        square_img.paste(cropped_img, (offset_x, offset_y), cropped_img)
        
        # Resize to clean standard size e.g. 512x512
        final_emblem = square_img.resize((512, 512), Image.Resampling.LANCZOS)
        final_emblem.save(output_path, "PNG")
        print(f"Saved transparent emblem to {output_path}")

        # Also save high-res cropped version
        high_res_path = output_path.replace(".png", "_hd.png")
        square_img.save(high_res_path, "PNG")
        print(f"Saved HD transparent emblem to {high_res_path}")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, "arandu_icon.png")
    out_emblem = os.path.join(base_dir, "arandu_emblem_transparent.png")
    
    process_emblem(icon_path, out_emblem)

    full_logo_path = os.path.join(base_dir, "arandu_logo_full.png")
    out_full = os.path.join(base_dir, "arandu_logo_full_transparent.png")
    if os.path.exists(full_logo_path):
        process_emblem(full_logo_path, out_full)
