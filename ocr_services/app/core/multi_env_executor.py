"""
Multi-Environment Executor
Điều phối các OCR engines chạy trong các conda environments khác nhau
"""

import os
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Literal

_log = logging.getLogger(__name__)


class MultiEnvExecutor:
    """
    Executor to run OCR engines in differents
    
    Conda Environments:
    - Vllm        -> DeepSeek OCR (vLLM + GPU)
    - vllm_doc    -> Docling OCR (vLLM + GPU) 
    - mineru      -> MinerU (CLI-based)
    """
    
    # Mapping engine -> conda environment
    CONDA_ENV_MAP = {
        "deepseek": "deepseek-ocr2",
        "docling": "vllm_doc", 
        "mineru": "mineru",
    }
    
    def __init__(self):
        """Initialize executor"""
        self.workers_dir = Path(__file__).parent.parent.parent / "workers"
        self.workers_dir.mkdir(exist_ok=True)
        
    def get_conda_env(self, engine_name: str) -> str:
        """
        Lấy tên conda environment tương ứng với engine
        
        Args:
            engine_name: Tên engine (deepseek, mineru, docling)
            
        Returns:
            Tên conda environment
        """
        env_name = self.CONDA_ENV_MAP.get(engine_name.lower())
        if not env_name:
            raise ValueError(f"Unknown engine: {engine_name}. Valid: {list(self.CONDA_ENV_MAP.keys())}")
        return env_name
    
    def execute_in_conda(
        self,
        engine_name: str,
        input_path: str,
        output_dir: str,
        job_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Thực thi OCR engine trong conda environment tương ứng
        
        Args:
            engine_name: Tên engine (deepseek, mineru, docling)
            input_path: Đường dẫn file input
            output_dir: Thư mục output
            job_id: ID của job
            **kwargs: Tham số bổ sung cho engine
            
        Returns:
            Dict chứa kết quả xử lý
        """
        conda_env = self.get_conda_env(engine_name)
        
        _log.info(f" Executing {engine_name.upper()} in conda env: {conda_env}")
        
        # Tạo temp file chứa config
        config = {
            "engine": engine_name,
            "input_path": str(input_path),
            "output_dir": str(output_dir),
            "job_id": job_id,
            **kwargs
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f, indent=2)
            config_path = f.name
        
        try:
            # Chạy script trong conda environment
            # Mapping engine name -> worker script name
            # docling -> docling_worker.py (tránh conflict với package docling)
            worker_name_map = {
                "deepseek": "deepseek.py",
                "mineru": "mineru.py",
                "docling": "docling_worker.py",  # Tên khác để tránh conflict
            }
            #define worker Scripts path
            worker_filename = worker_name_map.get(engine_name.lower(), f"{engine_name}.py")
            worker_script = self.workers_dir / worker_filename
            
            if not worker_script.exists():
                raise FileNotFoundError(f"Worker script not found: {worker_script}")
            
            # Command để activate conda và chạy script
            # Đường dẫn conda từ env variable, fallback sang default
            conda_base = os.getenv('CONDA_BASE', '/mnt/hdd1tb/miniconda3')
            cmd = f"""
source {conda_base}/etc/profile.d/conda.sh && \
conda activate {conda_env} && \
python {worker_script} {config_path}
"""
            
            _log.info(f"Running command in {conda_env}...")
            _log.debug(f"COMMAND: {cmd}")
            
            # Execute
            # Timeout is longer for first run (model initialization + inference)
            # Increased to 5400s (90 mins) to allow model loading
            result = subprocess.run(
                cmd,
                shell=True,
                executable='/bin/bash',
                capture_output=True,
                text=True,
                timeout=5400  # 90 minutes timeout for model loading + inference
            )
            
            # Log worker output (để debug)
            if result.stdout:
                _log.info(f"Worker output ({engine_name}):\n{result.stdout}")
            if result.stderr:
                _log.warning(f"Worker stderr ({engine_name}):\n{result.stderr}")
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                _log.error(f"Execution failed in {conda_env}: {error_msg}")
                raise RuntimeError(f"Engine {engine_name} failed: {error_msg}")
            
            # Parse output - workers save as {job_id}_result.json
            output_json = Path(output_dir) / f"{job_id}_result.json"
            if output_json.exists():
                with open(output_json, 'r', encoding='utf-8') as f:
                    result_data = json.load(f)
                # Clean up internal result file (not needed in final output)
                os.remove(str(output_json))
                return result_data
            else:
                _log.warning(f"RESULT FILE NOT FOUND: {output_json}")
                return {"status": "completed", "message": result.stdout}
        
        finally:
            # Cleanup temp config
            if os.path.exists(config_path):
                os.remove(config_path)
    
    def check_conda_envs(self) -> Dict[str, bool]:
        """
        Kiểm tra các conda environments có tồn tại không
        
        Returns:
            Dict mapping env_name -> exists (bool)
        """
        result = {}
        
        for engine, env_name in self.CONDA_ENV_MAP.items():
            try:
                cmd = f"""
source $(conda info --base)/etc/profile.d/conda.sh && \
conda env list | grep -w {env_name}
"""
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    executable='/bin/bash',
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                result[env_name] = proc.returncode == 0
                
            except Exception as e:
                _log.error(f"Error checking {env_name}: {e}")
                result[env_name] = False
        
        return result


# Singleton instance
_executor = None

#
def get_multi_env_executor() -> MultiEnvExecutor:
    """Get singleton instance của MultiEnvExecutor"""
    global _executor
    if _executor is None:
        _executor = MultiEnvExecutor()
    return _executor
