from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import json
import uuid
import time

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, 'assets')
OUTPUTS_DIR = os.path.join(BASE_DIR, 'outputs')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/health')
def health():
    model_path = os.path.join(BASE_DIR, 'models', 'yolo11n.pt')
    model_ready = os.path.exists(model_path)
    return jsonify({'status': 'ok', 'model_ready': model_ready})

@app.route('/api/jobs', methods=['POST'])
def create_job():
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'ok': False, 'error': 'No file selected'}), 400
    
    job_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    input_dir = os.path.join(job_dir, 'input')
    os.makedirs(input_dir, exist_ok=True)
    
    file_path = os.path.join(input_dir, file.filename)
    file.save(file_path)
    
    job_data = {
        'job_id': job_id,
        'project_name': request.form.get('project_name', 'CV Project'),
        'asset_name': file.filename,
        'status': 'created',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'started_at': None,
        'completed_at': None,
        'settings': {},
        'result_file': None,
        'error': None
    }
    
    with open(os.path.join(job_dir, 'job.json'), 'w', encoding='utf-8') as f:
        json.dump(job_data, f, indent=2)
    
    return jsonify({'ok': True, 'job_id': job_id})

@app.route('/api/jobs', methods=['GET'])
def list_jobs():
    jobs = []
    if os.path.exists(OUTPUTS_DIR):
        for job_id in os.listdir(OUTPUTS_DIR):
            job_dir = os.path.join(OUTPUTS_DIR, job_id)
            job_file = os.path.join(job_dir, 'job.json')
            if os.path.isfile(job_file):
                with open(job_file, 'r', encoding='utf-8') as f:
                    jobs.append(json.load(f))
    return jsonify({'ok': True, 'jobs': jobs})

@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    job_file = os.path.join(job_dir, 'job.json')
    
    if not os.path.isfile(job_file):
        return jsonify({'ok': False, 'error': 'Job not found'}), 404
    
    with open(job_file, 'r', encoding='utf-8') as f:
        job_data = json.load(f)
    
    return jsonify({'ok': True, 'job': job_data})

@app.route('/api/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    job_file = os.path.join(job_dir, 'job.json')
    
    if not os.path.isfile(job_file):
        return jsonify({'ok': False, 'error': 'Job not found'}), 404
    
    with open(job_file, 'r', encoding='utf-8') as f:
        job_data = json.load(f)
    
    if job_data['status'] in ['queued', 'running']:
        return jsonify({'ok': False, 'error': 'Cannot delete running job'}), 400
    
    import shutil
    shutil.rmtree(job_dir)
    
    return jsonify({'ok': True})

@app.route('/api/jobs/<job_id>/analyze', methods=['POST'])
def analyze_job(job_id):
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    job_file = os.path.join(job_dir, 'job.json')
    
    if not os.path.isfile(job_file):
        return jsonify({'ok': False, 'error': 'Job not found'}), 404
    
    with open(job_file, 'r', encoding='utf-8') as f:
        job_data = json.load(f)
    
    if job_data['status'] != 'created':
        return jsonify({'ok': False, 'error': 'Job already processed'}), 400
    
    job_data['status'] = 'running'
    job_data['started_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    
    with open(job_file, 'w', encoding='utf-8') as f:
        json.dump(job_data, f, indent=2)
    
    try:
        from cv_engine.video_processor import VideoProcessor
        from cv_engine.yolo_detector import YoloDetector
        from cv_engine.highlight_scorer import HighlightScorer
        
        input_dir = os.path.join(job_dir, 'input')
        keyframes_dir = os.path.join(job_dir, 'keyframes')
        result_dir = os.path.join(job_dir, 'result')
        os.makedirs(keyframes_dir, exist_ok=True)
        os.makedirs(result_dir, exist_ok=True)
        
        asset_path = os.path.join(input_dir, job_data['asset_name'])
        
        processor = VideoProcessor()
        video_info = processor.get_video_info(asset_path)
        frames, timestamps = processor.sample_video(asset_path, interval=1)
        
        detector = YoloDetector('models/yolo11n.pt')
        all_results = detector.detect_frames(frames)
        
        scorer = HighlightScorer()
        analysis_result = scorer.analyze(frames, all_results, timestamps, job_id)
        
        analysis_result['video_info'] = video_info
        
        result_file = os.path.join(result_dir, 'analysis_report.json')
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(analysis_result, f, indent=2)
        
        job_data['status'] = 'completed'
        job_data['completed_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        job_data['result_file'] = 'result/analysis_report.json'
        
    except Exception as e:
        job_data['status'] = 'failed'
        job_data['error'] = str(e)
    
    with open(job_file, 'w', encoding='utf-8') as f:
        json.dump(job_data, f, indent=2)
    
    return jsonify({'ok': True, 'status': job_data['status']})

def find_ffmpeg():
    import shutil
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path
    
    common_paths = [
        r'D:\Ffmpeg\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe',
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        r'D:\ffmpeg\bin\ffmpeg.exe',
    ]
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    return None

def get_scale_filter(aspect_ratio):
    if aspect_ratio == '9:16':
        return 'scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2'
    elif aspect_ratio == '1:1':
        return 'scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2'
    elif aspect_ratio == '16:9':
        return 'scale=1920:1080:force_original_aspect_ratio=decrease'
    else:
        return None

@app.route('/api/jobs/<job_id>/rough-cut', methods=['POST'])
def rough_cut(job_id):
    try:
        job_dir = os.path.join(OUTPUTS_DIR, job_id)
        job_file = os.path.join(job_dir, 'job.json')
        
        if not os.path.isfile(job_file):
            return jsonify({'ok': False, 'error': 'Job not found'}), 404
        
        with open(job_file, 'r', encoding='utf-8') as f:
            job_data = json.load(f)
        
        if job_data['status'] != 'completed':
            return jsonify({'ok': False, 'error': 'Job not completed'}), 400
        
        result_file = os.path.join(job_dir, job_data['result_file'])
        with open(result_file, 'r', encoding='utf-8') as f:
            analysis_result = json.load(f)
        
        input_path = os.path.join(job_dir, 'input', job_data['asset_name'])
        
        aspect_ratio = request.form.get('aspect_ratio', '16:9')
        scale_filter = get_scale_filter(aspect_ratio)
        
        output_suffix = {
            '16:9': 'landscape',
            '9:16': 'portrait',
            '1:1': 'square'
        }.get(aspect_ratio, 'landscape')
        output_path = os.path.join(job_dir, 'result', f'rough_cut_{job_id}_{output_suffix}.mp4')
        
        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            return jsonify({'ok': False, 'error': 'FFmpeg not found. Please install FFmpeg and add to PATH.'}), 500
        
        segments = analysis_result.get('recommended_segments', [])
        if segments:
            if len(segments) == 1:
                best_segment = segments[0]
                start = best_segment['start']
                end = best_segment['end']
                
                import subprocess
                cmd = [
                    ffmpeg_path, '-ss', str(start), '-to', str(end),
                    '-i', input_path,
                    '-vcodec', 'libx264', '-acodec', 'aac',
                    '-strict', 'experimental', '-y'
                ]
                if scale_filter:
                    cmd.extend(['-vf', scale_filter])
                cmd.append(output_path)
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    cmd_no_audio = [
                        ffmpeg_path, '-ss', str(start), '-to', str(end),
                        '-i', input_path,
                        '-vcodec', 'libx264', '-an',
                        '-y'
                    ]
                    if scale_filter:
                        cmd_no_audio.extend(['-vf', scale_filter])
                    cmd_no_audio.append(output_path)
                    
                    result_no_audio = subprocess.run(cmd_no_audio, capture_output=True, text=True)
                    if result_no_audio.returncode != 0:
                        return jsonify({'ok': False, 'error': f'FFmpeg error: {result.stderr}'}), 500
            else:
                import subprocess
                import tempfile
                
                temp_files = []
                has_audio = True
                
                for i, segment in enumerate(segments):
                    temp_output = os.path.join(tempfile.gettempdir(), f'temp_segment_{i}.mp4')
                    cmd = [
                        ffmpeg_path, '-ss', str(segment['start']), '-to', str(segment['end']),
                        '-i', input_path,
                        '-vcodec', 'libx264', '-acodec', 'aac',
                        '-strict', 'experimental', '-y'
                    ]
                    if scale_filter:
                        cmd.extend(['-vf', scale_filter])
                    cmd.append(temp_output)
                    
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        cmd_no_audio = [
                            ffmpeg_path, '-ss', str(segment['start']), '-to', str(segment['end']),
                            '-i', input_path,
                            '-vcodec', 'libx264', '-an',
                            '-y'
                        ]
                        if scale_filter:
                            cmd_no_audio.extend(['-vf', scale_filter])
                        cmd_no_audio.append(temp_output)
                        
                        result_no_audio = subprocess.run(cmd_no_audio, capture_output=True, text=True)
                        if result_no_audio.returncode != 0:
                            return jsonify({'ok': False, 'error': f'FFmpeg error: {result.stderr}'}), 500
                        has_audio = False
                    temp_files.append(temp_output)
                
                concat_file = os.path.join(tempfile.gettempdir(), f'concat_list.txt')
                with open(concat_file, 'w') as f:
                    for temp_file in temp_files:
                        f.write(f"file '{temp_file}'\n")
                
                cmd = [
                    ffmpeg_path, '-f', 'concat', '-safe', '0',
                    '-i', concat_file,
                    '-c', 'copy',
                    '-y', output_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    cmd_reencode = [
                        ffmpeg_path, '-f', 'concat', '-safe', '0',
                        '-i', concat_file,
                        '-vcodec', 'libx264', '-acodec', 'aac' if has_audio else '-an',
                        '-strict', 'experimental', '-y', output_path
                    ]
                    result_reencode = subprocess.run(cmd_reencode, capture_output=True, text=True)
                    if result_reencode.returncode != 0:
                        return jsonify({'ok': False, 'error': f'FFmpeg concat error: {result.stderr}'}), 500
                
                for temp_file in temp_files:
                    os.remove(temp_file)
                os.remove(concat_file)
        
        return jsonify({'ok': True, 'output_file': f'result/rough_cut_{job_id}_{output_suffix}.mp4', 'aspect_ratio': aspect_ratio})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/jobs/<job_id>/report', methods=['GET'])
def get_report(job_id):
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    job_file = os.path.join(job_dir, 'job.json')
    
    if not os.path.isfile(job_file):
        return jsonify({'ok': False, 'error': 'Job not found'}), 404
    
    with open(job_file, 'r', encoding='utf-8') as f:
        job_data = json.load(f)
    
    if job_data['status'] != 'completed':
        return jsonify({'ok': False, 'error': 'Job not completed'}), 400
    
    result_file = os.path.join(job_dir, job_data['result_file'])
    with open(result_file, 'r', encoding='utf-8') as f:
        analysis_result = json.load(f)
    
    return jsonify({'ok': True, 'report': analysis_result})

@app.route('/outputs/<job_id>/<path:filename>')
def serve_output(job_id, filename):
    job_dir = os.path.join(OUTPUTS_DIR, job_id)
    return send_from_directory(job_dir, filename)

if __name__ == '__main__':
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    app.run(host='127.0.0.1', port=7880, debug=True)