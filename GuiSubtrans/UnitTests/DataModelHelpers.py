from GuiSubtrans.ProjectDataModel import ProjectDataModel
from PySubtrans.Helpers.TestCases import AddTranslations, PrepareSubtitles
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleBatcher import SubtitleBatcher
from PySubtrans.SubtitleEditor import SubtitleEditor
from PySubtrans.Subtitles import Subtitles
from PySubtrans.SubtitleProject import SubtitleProject


def CreateTestDataModel(test_data : dict, options : Options|None = None) -> ProjectDataModel:
    """
    Creates a ProjectDataModel from test data.
    """
    options = options or Options()
    file : Subtitles = PrepareSubtitles(test_data, 'original')
    project = SubtitleProject(persistent = options.use_project_file)
    project.write_translation = False
    project.subtitles = file
    project.UpdateProjectSettings(options)
    datamodel = ProjectDataModel(project, options)
    datamodel.UpdateProviderSettings(SettingsType({"data" : test_data}))
    return datamodel

def CreateTestDataModelBatched(test_data : dict, options : Options|None = None, translated : bool = True) -> ProjectDataModel:
    """
    Creates a SubtitleBatcher from test data.
    """
    datamodel : ProjectDataModel = CreateTestDataModel(test_data, options)
    if not datamodel.project:
        raise ValueError("Project not created in datamodel")

    options = options or datamodel.project_options

    subtitles : Subtitles = datamodel.project.subtitles
    batcher = SubtitleBatcher(options.GetSettings())
    with SubtitleEditor(subtitles) as editor:
        editor.AutoBatch(batcher)

    if translated and 'translated' in test_data:
        AddTranslations(subtitles, test_data, 'translated')

    return datamodel

