from unittest.mock import MagicMock, patch

from app.services import classifier


def test_complexity_threshold_constant_removed():
    assert not hasattr(classifier, "COMPLEXITY_THRESHOLD")


class TestProbeDevice:
    def test_prefers_cuda(self):
        with patch("torch.cuda.is_available", return_value=True):
            assert classifier._probe_device().type == "cuda"

    def test_prefers_mps_over_cpu(self):
        mock_mps = MagicMock()
        mock_mps.is_available.return_value = True
        mock_mps.is_built.return_value = True
        with patch("torch.cuda.is_available", return_value=False), \
                patch.object(classifier.torch.backends, "mps", mock_mps, create=True):
            assert classifier._probe_device().type == "mps"

    def test_falls_back_to_cpu_when_nothing_available(self):
        mock_mps = MagicMock()
        mock_mps.is_available.return_value = False
        mock_mps.is_built.return_value = False
        with patch("torch.cuda.is_available", return_value=False), \
                patch.object(classifier.torch.backends, "mps", mock_mps, create=True):
            assert classifier._probe_device().type == "cpu"

    def test_never_raises_when_mps_attribute_absent(self):
        # Simulates an older torch with no torch.backends.mps at all: our
        # getattr(..., None) default takes the same branch as a real absent
        # attribute, without fighting torch's submodule re-import machinery.
        with patch("torch.cuda.is_available", return_value=False), \
                patch.object(classifier.torch.backends, "mps", None, create=True):
            assert classifier._probe_device().type == "cpu"


class TestSelectDeviceOverride:
    def test_auto_uses_probe(self):
        with patch.object(classifier.config, "TORCH_DEVICE", "auto"), \
                patch.object(classifier, "_probe_device", return_value=classifier.torch.device("cpu")) as probe:
            assert classifier._select_device().type == "cpu"
            probe.assert_called_once()

    def test_forces_cpu(self):
        with patch.object(classifier.config, "TORCH_DEVICE", "cpu"):
            assert classifier._select_device().type == "cpu"

    def test_forces_cuda_when_available(self):
        with patch.object(classifier.config, "TORCH_DEVICE", "cuda"), \
                patch("torch.cuda.is_available", return_value=True):
            assert classifier._select_device().type == "cuda"

    def test_cuda_override_falls_back_when_unavailable(self):
        with patch.object(classifier.config, "TORCH_DEVICE", "cuda"), \
                patch("torch.cuda.is_available", return_value=False), \
                patch.object(classifier, "_probe_device", return_value=classifier.torch.device("cpu")) as probe:
            assert classifier._select_device().type == "cpu"
            probe.assert_called_once()

    def test_forces_mps_when_available(self):
        mock_mps = MagicMock()
        mock_mps.is_available.return_value = True
        mock_mps.is_built.return_value = True
        with patch.object(classifier.config, "TORCH_DEVICE", "mps"), \
                patch.object(classifier.torch.backends, "mps", mock_mps, create=True):
            assert classifier._select_device().type == "mps"

    def test_mps_override_falls_back_when_unavailable(self):
        mock_mps = MagicMock()
        mock_mps.is_available.return_value = False
        mock_mps.is_built.return_value = False
        with patch.object(classifier.config, "TORCH_DEVICE", "mps"), \
                patch.object(classifier.torch.backends, "mps", mock_mps, create=True), \
                patch.object(classifier, "_probe_device", return_value=classifier.torch.device("cpu")) as probe:
            assert classifier._select_device().type == "cpu"
            probe.assert_called_once()

    def test_unrecognised_value_falls_back_to_probe(self):
        with patch.object(classifier.config, "TORCH_DEVICE", "tpu"), \
                patch.object(classifier, "_probe_device", return_value=classifier.torch.device("cpu")) as probe:
            assert classifier._select_device().type == "cpu"
            probe.assert_called_once()
