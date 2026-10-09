"""An in-memory stand-in for a boto3 S3 client (only the calls FORGE-X uses),
raising errors in botocore's shape: err.response["Error"]["Code"]."""
import io


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self, bucket="evidence", public=False):
        self.bucket, self.public, self.objects, self.calls = bucket, public, {}, []

    def _check(self, bucket):
        if bucket != self.bucket:
            raise FakeClientError("NoSuchBucket")

    def head_bucket(self, Bucket):
        self._check(Bucket)

    def get_bucket_policy_status(self, Bucket):
        self._check(Bucket)
        return {"PolicyStatus": {"IsPublic": self.public}}

    def put_object(self, Bucket, Key, Body, ContentLength=None, ContentType=None, IfNoneMatch=None,
                   ServerSideEncryption=None):
        self._check(Bucket)
        self.calls.append(("put_object", Key, IfNoneMatch, ServerSideEncryption))
        if IfNoneMatch == "*" and Key in self.objects:
            raise FakeClientError("PreconditionFailed")
        data = Body.read()
        assert ContentLength is None or ContentLength == len(data)
        self.objects[Key] = data

    def get_object(self, Bucket, Key):
        self._check(Bucket)
        if Key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        self._check(Bucket)
        if Key not in self.objects:
            raise FakeClientError("404")
        return {"ContentLength": len(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self._check(Bucket)
        self.objects.pop(Key, None)
