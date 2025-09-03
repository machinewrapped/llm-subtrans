import os
from PySubtitle.SubtitleBatcher import SubtitleBatcher
from PySubtitle.Subtitles import Subtitles
from PySubtitle.Helpers.Tests import RunTestOnAllSubtitleFiles, separator

def analyze_scenes(scenes):
    num_scenes = len(scenes)
    num_batches_list = []
    largest_batch_list = []
    smallest_batch_list = []
    average_batch_size_list = []

    for scene in scenes:
        num_batches = len(scene.batches)
        batch_sizes = [batch.size for batch in scene.batches]

        largest_batch = max(batch_sizes)
        smallest_batch = min(batch_sizes)
        average_batch_size = sum(batch_sizes) / num_batches

        num_batches_list.append(num_batches)
        largest_batch_list.append(largest_batch)
        smallest_batch_list.append(smallest_batch)
        average_batch_size_list.append(average_batch_size)

    return num_scenes, num_batches_list, largest_batch_list, smallest_batch_list, average_batch_size_list

def batcher_test(subtitles: Subtitles, logger, options):
    if not subtitles.originals:
        raise Exception("No original subtitles to batch")

    try:
        batcher = SubtitleBatcher(options)
        scenes = batcher.BatchSubtitles(subtitles.originals)
    except Exception as e:
        raise Exception(f"Error in batcher.BatchSubtitles: {e}")

    # Analyze scenes
    num_scenes, num_batches_list, largest_batch_list, smallest_batch_list, avg_batch_list = analyze_scenes(scenes)

    total_batches = sum(num_batches_list)
    total_largest = max(largest_batch_list)
    total_smallest = min(smallest_batch_list)
    total_avg = sum(avg_batch_list) / num_scenes

    logger.info(separator)
    logger.info(f"Total (min {options['min_batch_size']}, max {options['max_batch_size']}, scene {options['scene_threshold']})")
    logger.info(separator)
    logger.info(f"{'Total Batches':<25}{total_batches:<10}")
    logger.info(f"{'Total Largest Batch':<25}{total_largest:<10}")
    logger.info(f"{'Total Smallest Batch':<25}{total_smallest:<10}")
    logger.info(f"{'Average Batch Size':<25}{total_avg:<10.2f}")
    logger.info(separator)

def run_tests(directory_path, results_path):
    test_options = [
        { 'min_batch_size': 10, 'max_batch_size': 100, 'scene_threshold': 60 },
        { 'min_batch_size': 8, 'max_batch_size': 40, 'scene_threshold': 30 },
        { 'min_batch_size': 16, 'max_batch_size': 80, 'scene_threshold': 40 },
    ]

    RunTestOnAllSubtitleFiles(batcher_test, test_options, directory_path, results_path)

if __name__ == "__main__":
    directory_path = os.path.join(os.getcwd(), "test_subtitles")
    results_path = os.path.join(directory_path, "test_results")
    run_tests(directory_path, results_path)
