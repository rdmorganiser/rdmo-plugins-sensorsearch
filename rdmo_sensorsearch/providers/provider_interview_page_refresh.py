from rdmo.options.providers import Provider


class InterviewPageRefreshProvider(Provider):
    """Tell the RDMO interview to refetch the current page after saving a trigger."""

    search = False
    refresh = True

    def get_options(self, project, search=None, user=None, site=None):
        return []
