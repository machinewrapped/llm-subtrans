import unittest
from datetime import timedelta

from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleLine import SubtitleLine
from PySubtrans.Subtitles import Subtitles
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestSubtitleBuilder(LoggedTestCase):

    def setUp(self):
        """Set up test cases."""
        super().setUp()

    def test_empty_builder_initialization(self):
        """Test creating an empty SubtitleBuilder."""
        builder = SubtitleBuilder()
        subtitles = builder.Build()

        self.assertLoggedIsInstance("subtitles type", subtitles, Subtitles)

        self.assertLoggedEqual("subtitles.scenes length", 0, len(subtitles.scenes))

    def test_add_scene_creation(self):
        """Test adding a new scene."""
        builder = SubtitleBuilder()
        result = builder.AddScene(summary="Test scene")
        subtitles = builder.Build()

        self.assertLoggedIsInstance("AddScene return type", result, SubtitleBuilder)

        self.assertLoggedEqual("scenes count", 1, len(subtitles.scenes))

        scene = subtitles.scenes[0]
        self.assertLoggedEqual("scene number", 1, scene.number)

        self.assertLoggedEqual("scene summary", "Test scene", scene.summary)

    def test_automatic_batch_creation(self):
        """Test that batches are created automatically when scene is finalized."""
        builder = SubtitleBuilder()
        builder.AddScene()
        result = builder.BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Test line")

        self.assertLoggedIsInstance("AddLine return type", result, SubtitleBuilder)

        # Batches are created when scene is finalized
        subtitles = builder.Build()
        scene = subtitles.scenes[0]
        self.assertLoggedEqual("batches created automatically", 1, len(scene.batches))

        batch = scene.batches[0]
        self.assertLoggedEqual("batch number", 1, batch.number)

        self.assertLoggedEqual("batch has line", 1, len(batch.originals))

    def test_add_line_without_scene(self):
        """Test that adding a line without a scene automatically adds the scene."""
        builder = SubtitleBuilder()

        builder.BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Test")

        subtitles = builder.Build()
        self.assertLoggedEqual("scenes count", 1, len(subtitles.scenes))

    def test_add_line(self):
        """Test adding a subtitle line."""
        builder = SubtitleBuilder()
        builder.AddScene()

        result = builder.BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Test line")

        self.assertLoggedIsInstance("AddLine return type", result, SubtitleBuilder)

        subtitles = builder.Build()

        self.assertLoggedEqual("scenes count", 1, len(subtitles.scenes))

        self.assertLoggedEqual("batches count", 1, len(subtitles.scenes[0].batches))

        batch = subtitles.scenes[0].batches[0]
        self.assertLoggedEqual("batch originals count", 1, len(batch.originals))

        line = batch.originals[0]
        self.assertLoggedEqual("line number", 1, line.number)

        self.assertLoggedEqual("line text", "Test line", line.text)

    def test_add_lines_with_subtitle_line_objects(self):
        """Test adding multiple SubtitleLine objects."""
        builder = SubtitleBuilder()
        builder.AddScene()

        lines = [
            SubtitleLine.Construct(1, timedelta(seconds=1), timedelta(seconds=3), "Line 1"),
            SubtitleLine.Construct(2, timedelta(seconds=4), timedelta(seconds=6), "Line 2")
        ]

        result = builder.AddLines(lines)

        self.assertLoggedIsInstance("AddLines return type", result, SubtitleBuilder)

        # Batches are created when scene is finalized
        subtitles = builder.Build()
        batch = subtitles.scenes[0].batches[0]
        self.assertLoggedEqual("batch originals count", 2, len(batch.originals))

    def test_add_lines_with_tuples(self):
        """Test adding multiple lines as tuples."""
        builder = SubtitleBuilder()
        builder.AddScene()

        lines = [
            (timedelta(seconds=1), timedelta(seconds=3), "Line 1"),
            (timedelta(seconds=4), timedelta(seconds=6), "Line 2")
        ]

        builder.AddLines(lines)

        # Batches are created when scene is finalized
        subtitles = builder.Build()
        batch = subtitles.scenes[0].batches[0]
        self.assertLoggedEqual("batch originals count", 2, len(batch.originals))

        self.assertLoggedEqual("first line text", "Line 1", batch.originals[0].text)

    def test_multiple_scenes_and_batches(self):
        """Test creating multiple scenes and batches."""
        builder = SubtitleBuilder()

        (builder
         .AddScene(summary="Scene 1")
         .BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Line 1")
         .BuildLine(timedelta(seconds=4), timedelta(seconds=6), "Line 2")
         .AddScene(summary="Scene 2")
         .BuildLine(timedelta(seconds=65), timedelta(seconds=67), "Line 3")
        )

        # Finalize to create batches
        subtitles = builder.Build()
        self.assertLoggedEqual("scenes count", 2, len(subtitles.scenes))

        self.assertLoggedEqual("scene 1 batches count", 1, len(subtitles.scenes[0].batches))

        self.assertLoggedEqual("scene 2 batches count", 1, len(subtitles.scenes[1].batches))

    def test_automatic_batch_splitting(self):
        """Test that batches are automatically split when they exceed max_batch_size."""
        builder = SubtitleBuilder(max_batch_size=5)
        builder.AddScene()

        # Add many lines to trigger automatic batch splitting
        for i in range(1, 11):  # 10 lines
            builder.BuildLine(timedelta(seconds=i), timedelta(seconds=i+1), f"Line {i}")

        # Batching happens when scene is finalized
        subtitles = builder.Build()
        scene = subtitles.scenes[0]

        # Should have multiple batches due to intelligent splitting
        self.assertLoggedGreater("batches created", len(scene.batches), 1)

        # Verify all batches are within size limit
        for batch in scene.batches:
            self.assertLoggedLessEqual(
                f"batch {batch.number} size",
                len(batch.originals),
                5,
            )

    def test_no_split_when_within_limit(self):
        """Test that batches are not split when within max_batch_size."""
        builder = SubtitleBuilder(max_batch_size=10)
        builder.AddScene()

        # Add few lines that don't exceed max_batch_size
        for i in range(1, 6):  # 5 lines
            builder.BuildLine(timedelta(seconds=i), timedelta(seconds=i+1), f"Line {i}")

        # Batching happens when scene is finalized
        subtitles = builder.Build()
        scene = subtitles.scenes[0]

        self.assertLoggedEqual("single batch count", 1, len(scene.batches))

        self.assertLoggedEqual("batch size", 5, len(scene.batches[0].originals))

    def test_build_finalizes_subtitles(self):
        """Test that Build() properly finalizes the subtitles structure."""
        builder = SubtitleBuilder()

        subtitles = (builder
                    .AddScene()
                    .BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Test line")
                    .Build()
        )

        self.assertLoggedIsInstance("built subtitles type", subtitles, Subtitles)

        # Check that flattened originals are properly set
        self.assertLoggedIsNotNone("originals is not None", subtitles.originals)

        if subtitles.originals:
            self.assertLoggedEqual("originals count", 1, len(subtitles.originals))

    def test_fluent_api_chaining(self):
        """Test that all methods support fluent API chaining."""
        builder = SubtitleBuilder()

        # Test that all methods return SubtitleBuilder for chaining
        result = (builder
                 .AddScene(summary="Test scene")
                 .BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Hello")
                 .BuildLine(timedelta(seconds=4), timedelta(seconds=6), "World")
        )

        self.assertLoggedIsInstance("fluent API result type", result, SubtitleBuilder)

        # Verify the structure was built correctly
        subtitles = result.Build()

        self.assertLoggedEqual("scenes count", 1, len(subtitles.scenes))
        scene = subtitles.scenes[0]

        self.assertLoggedEqual("batches count", 1, len(scene.batches))
        batch = scene.batches[0]

        self.assertLoggedEqual("batch lines count", 2, len(batch.originals))

        batch_line_numbers = [line.number for line in batch.originals]
        self.assertLoggedSequenceEqual("batch line numbers", [1, 2], batch_line_numbers)

    def test_build_line_with_metadata(self):
        """Test BuildLine with metadata parameter."""
        builder = SubtitleBuilder()
        metadata = {"speaker": "John", "emotion": "happy"}

        builder.BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Hello", metadata)

        subtitles = builder.Build()
        line = subtitles.scenes[0].batches[0].originals[0]

        self.assertLoggedEqual("line metadata", metadata, line.metadata)

    def test_add_lines_with_metadata_tuples(self):
        """Test AddLines with 4-tuple format including metadata."""
        builder = SubtitleBuilder()
        builder.AddScene()

        metadata1 = {"speaker": "Alice"}
        metadata2 = {"speaker": "Bob", "volume": "loud"}
        lines = [
            (timedelta(seconds=1), timedelta(seconds=3), "Line 1", metadata1),
            (timedelta(seconds=4), timedelta(seconds=6), "Line 2", metadata2)
        ]

        builder.AddLines(lines)
        subtitles = builder.Build()
        batch = subtitles.scenes[0].batches[0]

        self.assertLoggedEqual("first line metadata", metadata1, batch.originals[0].metadata)

        self.assertLoggedEqual("second line metadata", metadata2, batch.originals[1].metadata)

    def test_edge_case_batch_sizes(self):
        """Test builder with edge case batch sizes."""
        builder = SubtitleBuilder(max_batch_size=1, min_batch_size=1)
        builder.BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Test 1")
        builder.BuildLine(timedelta(seconds=4), timedelta(seconds=6), "Test 2")

        subtitles = builder.Build()
        scene = subtitles.scenes[0]

        self.assertLoggedGreaterEqual("batches count with max_batch_size=1", len(scene.batches), 2)

        # Each batch should have at most 1 line
        for i, batch in enumerate(scene.batches):
            self.assertLoggedLessEqual(
                f"batch {i+1} size",
                len(batch.originals),
                1,
            )

if __name__ == '__main__':
    unittest.main()
