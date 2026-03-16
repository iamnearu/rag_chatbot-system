import os
import torch
from vllm import LLM, SamplingParams
from vllm.model_executor.models.registry import ModelRegistry
from app.core.engine.deepseek_model import DeepseekOCR2ForCausalLM
from app.core.ngram_norepeat import NoRepeatNGramLogitsProcessor
from app.config import MODEL_PATH, MAX_CONCURRENCY, SKIP_REPEAT

if torch.version.cuda == '11.8':
    os.environ["TRITON_PTXAS_PATH"] = "/usr/local/cuda-11.8/bin/ptxas"

os.environ['VLLM_USE_V1'] = '0'
os.environ["CUDA_VISIBLE_DEVICES"] = '0'

ModelRegistry.register_model("DeepseekOCR2ForCausalLM", DeepseekOCR2ForCausalLM)
#
def init_llm():
    """Initialize vLLM engine"""
    
    try:
        print(f" Đang khởi tạo vLLM với model: {MODEL_PATH}")  
        llm = LLM(
            model=MODEL_PATH,
            hf_overrides={"architectures": ["DeepseekOCR2ForCausalLM"]},
            block_size=256,  # Giảm từ 256
            enforce_eager=False,  # Tắt CUDA graphs
            trust_remote_code=True, 
            max_model_len=8192,  # Giảm từ 8192
            swap_space=4,  # Thêm CPU swap 4GB
            max_num_seqs=MAX_CONCURRENCY,
            tensor_parallel_size=1,
            gpu_memory_utilization=0.85,  # Giảm từ 0.9
            disable_mm_preprocessor_cache=True,
        )
        print(f"✅ vLLM initialized successfully!")
        return llm
    except Exception as e:
            print(f"❌ CẢNH BÁO: Không thể khởi tạo vLLM (DeepSeek).")
            print(f"❌ Chi tiết lỗi: {type(e).__name__}: {str(e)[:200]}")
            import traceback
            traceback.print_exc()
            print(f"❌ Worker sẽ chạy ở chế độ CHỈ DOCLING.")
            return None
def get_sampling_params():
    """Get sampling parameters - Optimized for Vietnamese OCR"""
    logits_processors = None
    
    if SKIP_REPEAT:
        logits_processors = [NoRepeatNGramLogitsProcessor(
            ngram_size=20, 
            window_size=50, 
            whitelist_token_ids={128821, 128822}
        )]
    
    sampling_params = SamplingParams(
        temperature=0.0,  # Deterministic output - ổn định nhất
        max_tokens=8192,
        logits_processors=logits_processors,
        skip_special_tokens=False,
        include_stop_str_in_output=True,
    )
    return sampling_params

# Global instances
llm = init_llm()
sampling_params = get_sampling_params()