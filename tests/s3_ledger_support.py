"""In-memory S3 conditional-write double; never contacts AWS."""
import hashlib
import io
import threading
from botocore.exceptions import ClientError


class FakeLedgerS3:
    def __init__(self):
        self.objects = {}
        self.lock = threading.Lock()
        self.puts = 0
        self.conflict_once = False
        self.fail = False

    def get_object(self, *, Bucket, Key):
        with self.lock:
            if self.fail:
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
            if (Bucket, Key) not in self.objects:
                raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
            data, etag = self.objects[Bucket, Key]
            return {"Body": io.BytesIO(data), "ETag": etag}

    def put_object(self, *, Bucket, Key, Body, IfMatch=None, IfNoneMatch=None, **kwargs):
        with self.lock:
            if self.fail:
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")
            prior = self.objects.get((Bucket, Key))
            if (self.conflict_once or (IfNoneMatch == "*" and prior)
                    or (IfMatch is not None and (not prior or prior[1] != IfMatch))):
                self.conflict_once = False
                raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
            assert IfMatch or IfNoneMatch == "*", "Unconditional ledger writes are forbidden"
            assert kwargs["ServerSideEncryption"] == "AES256"
            etag = '"' + hashlib.md5(Body).hexdigest() + '"'
            self.objects[Bucket, Key] = (Body, etag)
            self.puts += 1
            return {"ETag": etag}
