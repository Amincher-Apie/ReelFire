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
    return jsonify({'status': 'ok', 'model_ready': False})

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
        frames, timestamps = processor.sample_video(asset_path, interval=2)
        
        detector = YoloDetector('models/yolo11n.pt')
        all_results = detector.detect_frames(frames)
        
        scorer = HighlightScorer()
        analysis_result = scorer.analyze(frames, all_results, timestamps, job_id)
        
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

@app.route('/api/jobs/<job_id>/rough-cut', methods=['POST'])
def rough_cut(job_id):
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
    
    import ffmpeg
    input_path = os.path.join(job_dir, 'input', job_data['asset_name'])
    output_path = os.path.join(job_dir, 'result', f'rough_cut_{job_id}.mp4')
    
    segments = analysis_result.get('recommended_segments', [])
    if segments:
        start = segments[0]['start']
        end = segments[-1]['end']
        (
            ffmpeg
            .input(input_path, ss=start, to=end)
            .output(output_path, vcodec='libx264', acodec='aac')
            .run(quiet=True)
        )
    
    return jsonify({'ok': True, 'output_file': f'result/rough_cut_{job_id}.mp4'})

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