import cv2
import numpy as np
import os

input_video = r'd:\_Day08\assets\test2.mp4'

cap = cv2.VideoCapture(input_video)
if not cap.isOpened():
    print(f"无法打开视频: {input_video}")
    exit()

frame_count = 0
output_dir = 'debug_frames'
os.makedirs(output_dir, exist_ok=True)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break
    
    if frame_count % 10 == 0:
        h, w = frame.shape[:2]
        
        roi_y_start = int(h * 0.55)
        roi_y_end = int(h * 0.75)
        roi_x_start = int(w * 0.30)
        roi_x_end = int(w * 0.70)
        
        roi = frame[roi_y_start:roi_y_end, roi_x_start:roi_x_end]
        
        cv2.imwrite(os.path.join(output_dir, f'frame_{frame_count}_full.jpg'), frame)
        cv2.imwrite(os.path.join(output_dir, f'frame_{frame_count}_roi.jpg'), roi)
        
        b_roi = roi[:, :, 0]
        g_roi = roi[:, :, 1]
        r_roi = roi[:, :, 2]
        
        print(f"\n=== Frame {frame_count} ===")
        print(f"Frame size: {w}x{h}")
        print(f"ROI: ({roi_y_start},{roi_x_start})-({roi_y_end},{roi_x_end}) = {roi.shape[1]}x{roi.shape[0]}")
        print(f"BGR mean: B={np.mean(b_roi):.2f}, G={np.mean(g_roi):.2f}, R={np.mean(r_roi):.2f}")
        print(f"BGR max: B={np.max(b_roi)}, G={np.max(g_roi)}, R={np.max(r_roi)}")
        print(f"BGR min: B={np.min(b_roi)}, G={np.min(g_roi)}, R={np.min(r_roi)}")
        
        red_pixels = np.sum((r_roi > 120) & (g_roi < 80) & (b_roi < 80))
        print(f"Red pixels (R>120, G<80, B<80): {red_pixels}")
        
        red_pixels_loose = np.sum((r_roi > 80) & (g_roi < r_roi * 0.8) & (b_roi < r_roi * 0.8))
        print(f"Red pixels (loose): {red_pixels_loose}")
        
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        print(f"HSV mean: H={np.mean(hsv[:,:,0]):.2f}, S={np.mean(hsv[:,:,1]):.2f}, V={np.mean(hsv[:,:,2]):.2f}")
        
        lower_red1 = np.array([0, 50, 50])
        upper_red1 = np.array([15, 255, 255])
        lower_red2 = np.array([160, 50, 50])
        upper_red2 = np.array([180, 255, 255])
        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        hsv_red = np.sum((mask1 | mask2) > 0)
        print(f"HSV red pixels: {hsv_red}")
    
    frame_count += 1

cap.release()
print(f"\n调试图像已保存到 {output_dir}/")