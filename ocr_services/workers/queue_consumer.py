"""
RabbitMQ Consumer - Lắng nghe queue_upload và dispatch task

Đây là consumer chính, chạy liên tục để:
1. Lắng nghe queue_upload từ RabbitMQ
2. Khi có message → dispatch Celery task để xử lý

Usage:
    python -m workers.queue_consumer
"""

import json
import logging
import sys
import os
import pika
import signal

# Setup path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.config import RABBIT_URL, QUEUE_UPLOADS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class QueueUploadConsumer:
    """Consumer để lắng nghe queue_uploads"""
    
    def __init__(self):
        self.queue_name = QUEUE_UPLOADS
        self._connection = None
        self._channel = None
        self._running = True
        self._processed_ids = set()  # Track đã xử lý để tránh duplicate
    
    def connect(self):
        """Kết nối tới RabbitMQ"""
        logger.info(f"🔌 Connecting to RabbitMQ...")
        
        params = pika.URLParameters(RABBIT_URL)
        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()
        
        # Declare queue
        self._channel.queue_declare(queue=self.queue_name, durable=True)
        
        # Set QoS - chỉ nhận 1 message mỗi lần
        self._channel.basic_qos(prefetch_count=1)
        
        logger.info(f"✅ Connected to RabbitMQ")
        logger.info(f"📥 Listening on queue: {self.queue_name}")
    
    def callback(self, ch, method, properties, body):
        """Xử lý message nhận được"""
        try:
            message = json.loads(body)
            
            # Handle 2 formats:
            # 1. Raw JSON từ Upload Service: {"document_id": "...", ...}
            # 2. Celery task format: [[{"document_id": "..."}], {}, {"callbacks": null, ...}]
       #     
            actual_message = None
            
            if isinstance(message, dict) and 'document_id' in message:
                actual_message = message
                
            elif isinstance(message, list) and len(message) > 0:
                first_element = message[0]
                if isinstance(first_element, list) and len(first_element) > 0:
                    actual_message = first_element[0]
                elif isinstance(first_element, dict) and 'document_id' in first_element:
                    actual_message = first_element
            
            if not actual_message or 'document_id' not in actual_message:
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            
            doc_id = actual_message.get('document_id')
            
            # Check duplicate - skip nếu đã xử lý
            if doc_id in self._processed_ids:
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            
            self._processed_ids.add(doc_id)
            
            # Dispatch Celery task
            from app.tasks.tasks import consume_minio_document_message_task
            
            task = consume_minio_document_message_task.delay(actual_message)
            
            logger.info(f"📨 {doc_id[:8]}... → Task {task.id[:8]}... | {actual_message.get('filename')}")
            
            # Acknowledge message
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            
        except Exception as e:
            logger.error(f"❌ Error processing message: {e}", exc_info=True)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
    
    def start(self):
        """Bắt đầu consume messages"""
        self.connect()
        
        self._channel.basic_consume(
            queue=self.queue_name,
            on_message_callback=self.callback,
            auto_ack=False
        )
        
        logger.info("")
        logger.info("═══════════════════════════════════════════════════")
        logger.info("🚀 Queue Consumer Started")
        logger.info("═══════════════════════════════════════════════════")
        logger.info(f"Listening on: {self.queue_name}")
        logger.info("")
        logger.info("Waiting for messages... Press Ctrl+C to stop")
        logger.info("═══════════════════════════════════════════════════")
        logger.info("")
        
        try:
            self._channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("\n⏹️ Stopping consumer...")
            self._channel.stop_consuming()
        finally:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
            logger.info("✅ Consumer stopped")
    
    def stop(self):
        """Dừng consumer"""
        self._running = False
        if self._channel:
            self._channel.stop_consuming()


def main():
    """Main entry point"""
    print("")
    print("═══════════════════════════════════════════════════════════")
    print("🚀 OCR Queue Consumer")
    print("═══════════════════════════════════════════════════════════")
    print("")
    print("Flow:")
    print("  1️⃣  Upload Service upload file → MinIO (document-uploads)")
    print("  2️⃣  Upload Service gửi message → RabbitMQ (queue_upload)")
    print("  3️⃣  [THIS] Consumer nhận message → Dispatch Celery task")
    print("  4️⃣  Celery Worker xử lý: Download → OCR → Upload result")
    print("  5️⃣  Celery Worker gửi kết quả → RabbitMQ (queue_finished)")
    print("")
    print("Message format expected:")
    print('  {')
    print('    "document_id": "uuid-of-document",')
    print('    "filename": "file.pdf",')
    print('    "minio_object_name": "uuid/file.pdf",')
    print('    "minio_uri": "minio://document-uploads/uuid/file.pdf",')
    print('    "status": "uploaded"')
    print('  }')
    print("")
    print("═══════════════════════════════════════════════════════════")
    print("")
    
    consumer = QueueUploadConsumer()
    consumer.start()


if __name__ == "__main__":
    main()
