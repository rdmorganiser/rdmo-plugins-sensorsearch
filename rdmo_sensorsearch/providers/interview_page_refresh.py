from rdmo.options.providers import Provider


class InterviewPageRefreshProvider(Provider):
    """Expose an explicit option that applies configured page refresh actions."""

    """Tell the RDMO interview to refetch the current page after saving a trigger."""

    search = False
    refresh = True

    def get_options(self, project, search=None, user=None, site=None):
        return []
