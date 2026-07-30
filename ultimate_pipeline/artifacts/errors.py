class ArtifactError(Exception):
    pass


class ArtifactNotFoundError(ArtifactError):
    def __init__(self, path: str):
        super().__init__(f"Artifact not found: {path}")
        self.path = path


class ArtifactHashMismatchError(ArtifactError):
    def __init__(self, path: str, expected: str, actual: str):
        super().__init__(f"Hash mismatch for {path}: expected {expected}, got {actual}")
        self.path = path
        self.expected = expected
        self.actual = actual


class ConcurrentWriteError(ArtifactError):
    def __init__(self, path: str):
        super().__init__(f"Concurrent write detected for: {path}")
        self.path = path


class ManifestCorruptionError(ArtifactError):
    def __init__(self, path: str, detail: str):
        super().__init__(f"Manifest corrupted at {path}: {detail}")
        self.path = path
        self.detail = detail


class MutationDomainViolationError(ArtifactError):
    def __init__(self, domain: str, detail: str):
        super().__init__(f"Mutation domain violation in {domain}: {detail}")
        self.domain = domain
        self.detail = detail


class CandidateValidationError(ArtifactError):
    def __init__(self, candidate_id: str, detail: str):
        super().__init__(f"Candidate {candidate_id} validation failed: {detail}")
        self.candidate_id = candidate_id
        self.detail = detail


class PromotionError(ArtifactError):
    def __init__(self, candidate_id: str, detail: str):
        super().__init__(f"Promotion failed for {candidate_id}: {detail}")
        self.candidate_id = candidate_id
        self.detail = detail


class RecoveryError(ArtifactError):
    def __init__(self, detail: str):
        super().__init__(f"Recovery failed: {detail}")
        self.detail = detail
