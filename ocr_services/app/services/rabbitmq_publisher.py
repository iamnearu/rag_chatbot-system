"""
RabbitMQ Publisher - Gửi message sau khi xử lý xong

Queue:
- queue_finished: Gửi kết quả sau khi OCR hoàn thành
"""

import json
import logging
import pika
from typing import Dict, Any, Optional
from app.config import RABBIT_URL, QUEUE_FINISHED

_log = logging.getLogger(__name__)


class RabbitMQPublisher:
    """Publisher để gửi message vào RabbitMQ"""
    
    def __init__(self):
        self.queue_finished = QUEUE_FINISHED
    
    def _create_connection(self):
        """Tạo connection mới tới RabbitMQ (mỗi lần publish)"""
        params = pika.URLParameters(RABBIT_URL)
        # Set timeout cao hơn để tránh connection lost
        params.heartbeat = 0  # Disable heartbeat để tránh timeout
        params.blocked_connection_timeout = 300
        #
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        
        # Declare queue để đảm bảo tồn tại
        channel.queue_declare(queue=self.queue_finished, durable=True)
        
        return connection, channel
    
    def publish_finished(self, job_id: str, status: str, result_urls: Dict[str, str] = None, error: str = None) -> bool:
        """
        Gửi message vào queue_finished sau khi xử lý xong
        
        Args:
            job_id: ID của job
            status: "success" hoặc "failed"
            result_urls: Dict với markdown_url và json_url
            error: Error message nếu failed
            
        Returns:
            True nếu gửi thành công
            
        Message format:
        {
            "job_id": "abc-123",
            "status": "success",
            "result_urls": {
                "markdown_url": "minio://ocr-results/abc-123/result.md",
                "json_url": "minio://ocr-results/abc-123/result.json"
            },
            "error": null
        }
        """
        connection = None
        try:
            # Tạo connection mới mỗi lần publish để tránh stale connection
            connection, channel = self._create_connection()
            
            message = {
                "job_id": job_id,
                "status": status,
                "result_urls": result_urls or {},
                "error": error
            }
            
            channel.basic_publish(
                exchange='',
                routing_key=self.queue_finished,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Persistent message
                    content_type='application/json'
                )
            )
            
            _log.info(f"✅ Published to {self.queue_finished}: job_id={job_id}, status={status}")
            return True
            
        except Exception as e:
            _log.error(f"❌ Failed to publish to {self.queue_finished}: {e}")
            return False
            
        finally:
            # Luôn đóng connection sau khi publish
            if connection and not connection.is_closed:
                try:
                    connection.close()
                except:
                    pass


# Singleton instance
_publisher = None


def get_publisher() -> RabbitMQPublisher:
    """Get publisher instance (singleton)"""
    global _publisher
    if _publisher is None:
        _publisher = RabbitMQPublisher()
    return _publisher


def publish_job_finished(job_id: str, status: str, result_urls: Dict[str, str] = None, error: str = None) -> bool:
    """
    Helper function để publish message
    
    Example:
        publish_job_finished("abc-123", "success", {"markdown_url": "...", "json_url": "..."})
    """
    publisher = get_publisher()
    return publisher.publish_finished(job_id, status, result_urls, error)


def send_finished_notification(job_id: str) -> bool:
    """
    Gửi thông báo hoàn tất Job tới hàng đợi 'queue_finished'.
    Dùng để UI hoặc các service khác cập nhật trạng thái thời gian thực.
    
    Legacy function - wrapper cho publish_job_finished với status="success"
    """
    return publish_job_finished(job_id, status="success")
