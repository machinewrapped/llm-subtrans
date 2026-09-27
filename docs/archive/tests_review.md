# Tests Review

This document evaluates the tests in the `tests/` directory as of this change.

Unless otherwise noted, the **Comprehensive** column is marked `Partial` to reflect that most suites concentrate on the most critical behaviours and leave some exotic edge cases for future extension.

## tests/GuiTests/test_BatchCommands.py

_Summary_: Validates batch command sequencing across several scenarios; primarily covers happy paths, so add failure handling cases to extend coverage.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_BatchCommands` | Yes | Yes | Yes | Partial | Keep | |

## tests/GuiTests/test_DataModel.py

_Summary_: Exercises data model isolation behaviours; consider adding tests for concurrent modifications to increase confidence.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_ProjectOptionsDecoupling` | Yes | Yes | Yes | Partial | Keep | |
| `test_ProjectOptionsIsolation` | Yes | Yes | Yes | Partial | Keep | |
| `test_ProviderSettingsIsolation` | Yes | Yes | Yes | Partial | Keep | |
| `test_UpdateProjectSettings` | Yes | Yes | Yes | Partial | Keep | |
| `test_UpdateSettingsWithNoneProject` | Yes | Yes | Yes | Partial | Keep | |

## tests/GuiTests/test_DeleteLinesCommand.py

_Summary_: Covers deletion flow for GUI command; could add assertions around undo/redo or error messaging for completeness.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_DeleteLinesCommand` | Yes | Yes | Yes | Partial | Keep | |

## tests/GuiTests/test_EditCommands.py

_Summary_: Aggregates multiple edit commands; splitting into focused tests or adding negative cases would improve comprehensiveness.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_Commands` | Yes | Yes | Yes | Partial | Keep | |

## tests/GuiTests/test_MergeLinesCommand.py

_Summary_: Validates merge command integration; further coverage of boundary conditions (single line, already merged) would be useful.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_MergeLinesCommand` | Yes | Yes | Yes | Partial | Keep | |

## tests/GuiTests/test_MergeSplitCommands.py

_Summary_: Covers merge/split orchestration; partial comprehensiveness because it omits error and concurrency paths.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_Commands` | Yes | Yes | Yes | Partial | Keep | |

## tests/GuiTests/test_ReparseTranslationCommand.py

_Summary_: Ensures reparse command updates model correctly; consider adding failure path when parser raises.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_ReparseTranslationsCommand` | Yes | Yes | Yes | Partial | Keep | |

## tests/GuiTests/test_StartTranslationCommand.py

_Summary_: Exercises command queueing under different options; partial coverage of error states such as provider failures.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_StartTranslationCommand` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_ChineseDinner.py

_Summary_: Integration-heavy walkthrough of a sample project; long but meaningful, though still partial because rare edge cases are not all enumerated.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_ChineseDinner` | Yes | Yes | Yes | Partial | Keep | |
| `test_SubtitleBatches` | Yes | Yes | Yes | Partial | Keep | |
| `test_SubtitleEditor_UpdateLine` | Yes | Yes | Yes | Partial | Keep | |
| `test_SubtitleLine` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_Options.py

_Summary_: Comprehensive suite for Options and SettingsType APIs; largely correct but could add coverage for per-provider edge cases and nested validation errors.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_add_method` | Yes | Yes | Yes | Partial | Keep | |
| `test_build_user_prompt` | Yes | Yes | Yes | Partial | Keep | |
| `test_build_user_prompt_empty_values` | Yes | Yes | Yes | Partial | Keep | |
| `test_current_provider_settings_missing_provider` | Yes | Yes | Yes | Partial | Keep | |
| `test_current_provider_settings_no_provider` | Yes | Yes | Yes | Partial | Keep | |
| `test_default_initialization` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_bool` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_bool_setting` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_bool_setting_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_dict` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_float` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_float_setting` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_float_setting_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_instructions` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_int` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_int_setting` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_int_setting_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_list` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_list_setting` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_list_setting_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_method` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_optional_setting` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_optional_setting_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_settings` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_str` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_str_list` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_str_setting` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_string_list_setting` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_timedelta` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_timedelta_setting` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_timedelta_setting_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialise_instructions_success` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialise_provider_settings` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialization_dict_and_kwargs` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialization_with_dict` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialization_with_kwargs` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialization_with_options_object` | Yes | Yes | Yes | Partial | Keep | |
| `test_load_settings_file_not_exists` | Yes | Yes | Yes | Partial | Keep | |
| `test_load_settings_success` | Yes | Yes | Yes | Partial | Keep | |
| `test_model_property` | Yes | Yes | Yes | Partial | Keep | |
| `test_none_values_filtered` | Yes | Yes | Yes | Partial | Keep | |
| `test_properties` | Yes | Yes | Yes | Partial | Keep | |
| `test_provider_setter` | Yes | Yes | Yes | Partial | Keep | |
| `test_provider_settings_nested_updates` | Yes | Yes | Yes | Partial | Keep | |
| `test_save_settings_success` | Yes | Yes | Yes | Partial | Keep | |
| `test_set_method` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_method_with_dict` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_method_with_options` | Yes | Yes | Yes | Partial | Keep | |
| `test_validate_setting_type` | Yes | Yes | Yes | Partial | Keep | |
| `test_validate_setting_type_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_version_update_migration` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_Parse.py

_Summary_: Focused unit tests for parsing helpers; consider adding malformed input variants for ParseNames beyond simple empties.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_GetValueFromName` | Yes | Yes | Yes | Partial | Keep | |
| `test_GetValueName` | Yes | Yes | Yes | Partial | Keep | |
| `test_ParseDelayFromHeader` | Yes | Yes | Yes | Partial | Keep | |
| `test_ParseNames` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_PySubtrans.py

_Summary_: Covers high-level convenience functions; extend to include streaming failure scenarios and translator reuse errors.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_batch_subtitles_required_for_translation` | Yes | Yes | Yes | Partial | Keep | |
| `test_explicit_prompt_overrides_instruction_file` | Yes | Yes | Yes | Partial | Keep | |
| `test_init_project_batches_on_creation` | Yes | Yes | Yes | Partial | Keep | |
| `test_init_subtitles_auto_batches` | Yes | Yes | Yes | Partial | Keep | |
| `test_init_translation_provider_reuse` | Yes | Yes | Yes | Partial | Keep | |
| `test_init_translation_provider_updates_provider` | Yes | Yes | Yes | Partial | Keep | |
| `test_init_translator_respects_user_modifications` | Yes | Yes | Yes | Partial | Keep | |
| `test_instruction_file_without_explicit_prompt` | Yes | Yes | Yes | Partial | Keep | |
| `test_json_workflow_with_events` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_SsaFileHandler.py

_Summary_: Extensive SSA handler coverage; still partial for exotic tags or malformed fonts, so consider targeted additions.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_compose_lines_basic` | Yes | Yes | Yes | Partial | Keep | |
| `test_compose_lines_with_line_breaks` | Yes | Yes | Yes | Partial | Keep | |
| `test_composite_tags_with_basic_formatting` | Yes | Yes | Yes | Partial | Keep | |
| `test_comprehensive_ssa_tag_preservation` | Yes | Yes | Yes | Partial | Keep | |
| `test_detect_ssa_format` | Yes | Yes | Yes | Partial | Keep | |
| `test_formatting_round_trip_preservation` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_file_extensions` | Yes | Yes | Yes | Partial | Keep | |
| `test_html_to_ssa_formatting_conversion` | Yes | Yes | Yes | Partial | Keep | |
| `test_load_file` | Yes | Yes | Yes | Partial | Keep | |
| `test_parse_empty_events_section` | Yes | Yes | Yes | Partial | Keep | |
| `test_parse_invalid_ssa_content` | Yes | Yes | Yes | Partial | Keep | |
| `test_parse_string_basic` | Yes | Yes | Yes | Partial | Keep | |
| `test_round_trip_conversion` | Yes | Yes | Yes | Partial | Keep | |
| `test_ssa_to_html_formatting_conversion` | Yes | Yes | Yes | Partial | Keep | |
| `test_subtitle_line_to_pysubs2_time_conversion` | Yes | Yes | Yes | Partial | Keep | |
| `test_tag_extraction_functions` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_Streaming.py

_Summary_: Exercises streaming client flows including errors; could add timeout and retry scenarios for completeness.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_api_error_handling` | Yes | Yes | Yes | Partial | Keep | |
| `test_concurrent_streaming_requests` | Yes | Yes | Yes | Partial | Keep | |
| `test_network_interruption_handling` | Yes | Yes | Yes | Partial | Keep | |
| `test_partial_response_processing` | Yes | Yes | Yes | Partial | Keep | |
| `test_streaming_event_handling` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_Substitutions.py

_Summary_: Validates substitution parsing and execution; add stress cases with overlapping keys to extend coverage.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_ParseSubstitutions` | Yes | Yes | Yes | Partial | Keep | |
| `test_PerformSubstitutions` | Yes | Yes | Yes | Partial | Keep | |
| `test_PerformSubstitutionsAuto` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_SubtitleBuilder.py

_Summary_: Covers builder API across scenes and batches; consider additional assertions for invalid input handling.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_add_line` | Yes | Yes | Yes | Partial | Keep | |
| `test_add_line_without_scene` | Yes | Yes | Yes | Partial | Keep | |
| `test_add_lines_with_metadata_tuples` | Yes | Yes | Yes | Partial | Keep | |
| `test_add_lines_with_subtitle_line_objects` | Yes | Yes | Yes | Partial | Keep | |
| `test_add_lines_with_tuples` | Yes | Yes | Yes | Partial | Keep | |
| `test_add_scene_creation` | Yes | Yes | Yes | Partial | Keep | |
| `test_automatic_batch_creation` | Yes | Yes | Yes | Partial | Keep | |
| `test_automatic_batch_splitting` | Yes | Yes | Yes | Partial | Keep | |
| `test_build_finalizes_subtitles` | Yes | Yes | Yes | Partial | Keep | |
| `test_build_line_with_metadata` | Yes | Yes | Yes | Partial | Keep | |
| `test_edge_case_batch_sizes` | Yes | Yes | Yes | Partial | Keep | |
| `test_empty_builder_initialization` | Yes | Yes | Yes | Partial | Keep | |
| `test_fluent_api_chaining` | Yes | Yes | Yes | Partial | Keep | |
| `test_multiple_scenes_and_batches` | Yes | Yes | Yes | Partial | Keep | |
| `test_no_split_when_within_limit` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_SubtitleEditor.py

_Summary_: Large suite hitting editor operations; meaningful but still partial because multi-user concurrency and undo cases are uncovered.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_add_scene` | Yes | Yes | Yes | Partial | Keep | |
| `test_add_translation_via_batch` | Yes | Yes | Yes | Partial | Keep | |
| `test_autobatch_functionality` | Yes | Yes | Yes | Partial | Keep | |
| `test_context_manager_functionality` | Yes | Yes | Yes | Partial | Keep | |
| `test_context_manager_with_real_subtitles` | Yes | Yes | Yes | Partial | Keep | |
| `test_delete_lines` | Yes | Yes | Yes | Partial | Keep | |
| `test_delete_lines_nonexistent` | Yes | Yes | Yes | Partial | Keep | |
| `test_duplicate_originals_as_translations` | Yes | Yes | Yes | Partial | Keep | |
| `test_duplicate_originals_fails_with_existing_translations` | Yes | Yes | Yes | Partial | Keep | |
| `test_exit_callback_exception_propagates` | Yes | Yes | Yes | Partial | Keep | |
| `test_exit_callback_invoked_on_failure` | Yes | Yes | Yes | Partial | Keep | |
| `test_exit_callback_invoked_on_success` | Yes | Yes | Yes | Partial | Keep | |
| `test_merge_lines_in_batch` | Yes | Yes | Yes | Partial | Keep | |
| `test_merge_scenes` | Yes | Yes | Yes | Partial | Keep | |
| `test_merge_scenes_invalid_input` | Yes | Yes | Yes | Partial | Keep | |
| `test_renumber_scenes` | Yes | Yes | Yes | Partial | Keep | |
| `test_sanitise_removes_invalid_content` | Yes | Yes | Yes | Partial | Keep | |
| `test_split_scene` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_batch_context` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_invalid_line` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_invalid_timing` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_metadata` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_multiple_fields` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_no_change` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_text` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_timing` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_timing_with_translation_sync` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_translation_existing` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_line_translation_new` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_scene_context` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_SubtitleFormatRegistry.py

_Summary_: Robust coverage of registry behaviours; remaining comprehensiveness gaps are around dynamic plugin discovery failures.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_AutoDiscovery` | Yes | Yes | Yes | Partial | Keep | |
| `test_CaseInsensitiveExtensions` | Yes | Yes | Yes | Partial | Keep | |
| `test_ClearMethod` | Yes | Yes | Yes | Partial | Keep | |
| `test_CreateHandler` | Yes | Yes | Yes | Partial | Keep | |
| `test_CreateHandlerWithEmptyExtension` | Yes | Yes | Yes | Partial | Keep | |
| `test_CreateHandlerWithFilename` | Yes | Yes | Yes | Partial | Keep | |
| `test_CreateHandlerWithInvalidFilename` | Yes | Yes | Yes | Partial | Keep | |
| `test_CreateHandlerWithNoExtensionOrFilename` | Yes | Yes | Yes | Partial | Keep | |
| `test_DetectAssFormatWithTxtExtension` | Yes | Yes | Yes | Partial | Keep | |
| `test_DetectFormatAndLoadFile` | Yes | Yes | Yes | Partial | Keep | |
| `test_DetectFormatAndLoadFileError` | Yes | Yes | Yes | Partial | Keep | |
| `test_DetectFormatAndLoadFileUnicodeError` | Yes | Yes | Yes | Partial | Keep | |
| `test_DetectSrtFormatWithTxtExtension` | Yes | Yes | Yes | Partial | Keep | |
| `test_DetectSsaFormatWithAssExtension` | Yes | Yes | Yes | Partial | Keep | |
| `test_DisableAutodiscovery` | Yes | Yes | Yes | Partial | Keep | |
| `test_DiscoverMethod` | Yes | Yes | Yes | Partial | Keep | |
| `test_DoubleDiscoveryBehavior` | Yes | Yes | Yes | Partial | Keep | |
| `test_DuplicateRegistrationPriority` | Yes | Yes | Yes | Partial | Keep | |
| `test_EnableAutodiscovery` | Yes | Yes | Yes | Partial | Keep | |
| `test_EnsureDiscoveredBehavior` | Yes | Yes | Yes | Partial | Keep | |
| `test_EnumerateFormats` | Yes | Yes | Yes | Partial | Keep | |
| `test_FormatDetectionNonexistentFile` | Yes | Yes | Yes | Partial | Keep | |
| `test_FormatDetectionPreservesOriginalMetadata` | Yes | Yes | Yes | Partial | Keep | |
| `test_FormatDetectionWithBinaryFile` | Yes | Yes | Yes | Partial | Keep | |
| `test_FormatDetectionWithEmptyFile` | Yes | Yes | Yes | Partial | Keep | |
| `test_FormatDetectionWithMalformedFile` | Yes | Yes | Yes | Partial | Keep | |
| `test_FormatDetectionWithNonUtf8AssFile` | Yes | Yes | Yes | Partial | Keep | |
| `test_FormatDetectionWithNonUtf8SrtFile` | Yes | Yes | Yes | Partial | Keep | |
| `test_GetFormatFromFilename` | Yes | Yes | Yes | Partial | Keep | |
| `test_ListAvailableFormats` | Yes | Yes | Yes | Partial | Keep | |
| `test_ListAvailableFormatsEmpty` | Yes | Yes | Yes | Partial | Keep | |
| `test_RegisterHandlerWithLowerPriority` | Yes | Yes | Yes | Partial | Keep | |
| `test_UnknownExtension` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_SubtitleProject.py

_Summary_: Covers project lifecycle operations; extend to include failure to write files and concurrent saves.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_default_initialization` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_backup_filepath` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_editor_exception_does_not_mark_project_dirty` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_editor_marks_project_dirty` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_project_filepath` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_project_settings` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialise_project_existing_subtrans` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialise_project_existing_subtrans_reload` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialise_project_new_srt` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialise_project_with_explicit_output_path` | Yes | Yes | Yes | Partial | Keep | |
| `test_persistent_initialization` | Yes | Yes | Yes | Partial | Keep | |
| `test_properties` | Yes | Yes | Yes | Partial | Keep | |
| `test_save_and_reload_project_preserves_settings` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_output_path` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_project_settings_legacy` | Yes | Yes | Yes | Partial | Keep | |
| `test_update_project_settings_normal` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_SubtitleProjectFormats.py

_Summary_: Thorough format conversion checks; consider performance or extremely large file scenarios for full coverage.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_AssColorHandling` | Yes | Yes | Yes | Partial | Keep | |
| `test_AssHandlerBasicFunctionality` | Yes | Yes | Yes | Partial | Keep | |
| `test_AssInlineFormatting` | Yes | Yes | Yes | Partial | Keep | |
| `test_AssLineBreaksHandling` | Yes | Yes | Yes | Partial | Keep | |
| `test_AssOverrideTags` | Yes | Yes | Yes | Partial | Keep | |
| `test_AssRoundtripPreservation` | Yes | Yes | Yes | Partial | Keep | |
| `test_AssToSrtConversion` | Yes | Yes | Yes | Partial | Keep | |
| `test_AutoDetectAss` | Yes | Yes | Yes | Partial | Keep | |
| `test_AutoDetectSrt` | Yes | Yes | Yes | Partial | Keep | |
| `test_ConversionWithProjectSerialization` | Yes | Yes | Yes | Partial | Keep | |
| `test_JsonSerializationRoundtrip` | Yes | Yes | Yes | Partial | Keep | |
| `test_ProjectFileRoundtripPreservesHandler` | Yes | Yes | Yes | Partial | Keep | |
| `test_SrtHandlerBasicFunctionality` | Yes | Yes | Yes | Partial | Keep | |
| `test_SrtToAssConversion` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_SubtitleValidator.py

_Summary_: Validates validator error reporting; add mixed-language and whitespace-only cases to broaden coverage.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_ValidateBatch_adds_untranslated_error` | Yes | Yes | Yes | Partial | Keep | |
| `test_ValidateBatch_includes_translation_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_ValidateTranslations_detects_errors` | Yes | Yes | Yes | Partial | Keep | |
| `test_ValidateTranslations_empty` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_Subtitles.py

_Summary_: Exercises helper functions for subtitles; extend with stress tests for extremely long subtitles or unusual punctuation.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_FindSplitPoint` | Yes | Yes | Yes | Partial | Keep | |
| `test_GetProportionalDuration` | Yes | Yes | Yes | Partial | Keep | |
| `test_MergeSubtitles` | Yes | Yes | Yes | Partial | Keep | |
| `test_MergeTranslations` | Yes | Yes | Yes | Partial | Keep | |
| `test_Postprocess` | Yes | Yes | Yes | Partial | Keep | |
| `test_Preprocess` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_Time.py

_Summary_: Covers time conversions thoroughly; only missing coverage around overflow/negative parsing edge cases.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_GetTimeDelta` | Yes | Yes | Yes | Partial | Keep | |
| `test_TimeDeltaToText` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_Translator.py

_Summary_: Integration tests for translator events; add tests for retry/backoff logic to extend coverage.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_PostProcessTranslation` | Yes | Yes | Yes | Partial | Keep | |
| `test_SubtitleTranslator` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_VttFileHandler.py

_Summary_: Strong coverage of VTT parsing and composition; still partial for malformed cue settings combinations.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_composition_variations` | Yes | Yes | Yes | Partial | Keep | |
| `test_cue_settings_preservation` | Yes | Yes | Yes | Partial | Keep | |
| `test_detect_vtt_format` | Yes | Yes | Yes | Partial | Keep | |
| `test_get_file_extensions` | Yes | Yes | Yes | Partial | Keep | |
| `test_load_file` | Yes | Yes | Yes | Partial | Keep | |
| `test_note_block_without_inline_text` | Yes | Yes | Yes | Partial | Keep | |
| `test_parse_invalid_vtt_content` | Yes | Yes | Yes | Partial | Keep | |
| `test_parse_string_basic` | Yes | Yes | Yes | Partial | Keep | |
| `test_round_trip_conversion` | Yes | Yes | Yes | Partial | Keep | |
| `test_speaker_voice_tags` | Yes | Yes | Yes | Partial | Keep | |
| `test_style_blocks_preservation` | Yes | Yes | Yes | Partial | Keep | |
| `test_timestamp_formatting_conversion` | Yes | Yes | Yes | Partial | Keep | |
| `test_voice_tag_metadata_extraction` | Yes | Yes | Yes | Partial | Keep | |
| `test_voice_tag_round_trip` | Yes | Yes | Yes | Partial | Keep | |
| `test_voice_tag_stripping` | Yes | Yes | Yes | Partial | Keep | |
| `test_vtt_cue_id_preservation` | Yes | Yes | Yes | Partial | Keep | |
| `test_vtt_parsing_variations` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_localization.py

_Summary_: Validates locale switching; extend to include pluralisation and ICU fallback behaviours.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_available_locales_and_display_name` | Yes | Yes | Yes | Partial | Keep | |
| `test_initialize_default_english` | Yes | Yes | Yes | Partial | Keep | |
| `test_missing_language_fallback` | Yes | Yes | Yes | Partial | Keep | |
| `test_placeholder_formatting` | Yes | Yes | Yes | Partial | Keep | |
| `test_switch_to_spanish_and_back` | Yes | Yes | Yes | Partial | Keep | |

## tests/PySubtransTests/test_text.py

_Summary_: Covers text helpers widely; could add tests for extremely large inputs and mixed scripts to extend coverage.


| Test | Meaningful | Useful | Correct | Comprehensive | Recommendation | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `test_BreakDialogOnOneLine` | Yes | Yes | Yes | Partial | Keep | |
| `test_BreakLongLines` | Yes | Yes | Yes | Partial | Keep | |
| `test_ContainsTags` | Yes | Yes | Yes | Partial | Keep | |
| `test_EnsureFullWidthPunctuation` | Yes | Yes | Yes | Partial | Keep | |
| `test_ExtractTag` | Yes | Yes | Yes | Partial | Keep | |
| `test_ExtractTaglist` | Yes | Yes | Yes | Partial | Keep | |
| `test_IsTextContentEqual` | Yes | Yes | Yes | Partial | Keep | |
| `test_LimitTextLength` | Yes | Yes | Yes | Partial | Keep | |
| `test_Linearise` | Yes | Yes | Yes | Partial | Keep | |
| `test_NormaliseDialogTags` | Yes | Yes | Yes | Partial | Keep | |
| `test_RemoveFillerWords` | Yes | Yes | Yes | Partial | Keep | |
| `test_RemoveWhitespaceAndPunctuation` | Yes | Yes | Yes | Partial | Keep | |
| `test_SanitiseSummary` | Yes | Yes | Yes | Partial | Keep | |

