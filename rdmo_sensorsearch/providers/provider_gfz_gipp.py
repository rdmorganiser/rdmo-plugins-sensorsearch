import logging
import re
from rdmo_sensorsearch.providers.base import BaseSensorProvider

logger = logging.getLogger(__name__)


class GeophysicalInstrumentPoolPotsdamProvider(BaseSensorProvider):
    """
    Searches the GFZ Potsdam Geophysical Instrument Pool (GIPP) for instruments
    and returns options.

    This provider queries the GIPP API for a list of all instruments and then
    filters based on a provided search term. It constructs option objects
    containing the instrument code and a unique ID derived from the
    instrument's ID in the GIPP.

    Attributes:
        id_prefix (str):    Prefix for generated option IDs. Defaults to
                            "gfzgipp". This id_prefix can be used by handlers
                            (post_save) to query more data, when using
                            different instances.
        text_prefix (str):  Prefix for displayed option text. Defaults to
                            "GIPP:".
        max_hits (int):     Maximum number of search results to return.
                            Defaults to 10.
        base_url (str):     Base URL for the GIPP API endpoint. Defaults to
                            "https://gipp.gfz-potsdam.de/instruments".
    """

    id_prefix = "gfzgipp"
    text_prefix = "GIPP:"
    max_hits = 10
    base_url = "https://gipp.gfz-potsdam.de/instruments"

    def get_all_instruments(self) -> dict:
        """
        Retrieves a list of all instruments from the GIPP API.

        Returns:
            The JSON response containing instrument data as retrieved from the
            GIPP API, or an empty list if the request fails.
        """
        url = self.base_url + "/index.json?limit=10000&program=MOSES"
        return self.fetch_json(url)

    def get_options(self, project, search=None, user=None, site=None):
        """
        Searches the GIPP instrument list for instruments matching the provided
        search term.

        Does a simple search through the list of instruments retrieved from the
        GIPP API.

        Args:
            project (Project):      The RDMO project object.
            search (str, optional): Search term to query the GIPP instruments.
                                    Defaults to None.
            user (User, optional):  Current user object. Not used in this
                                    implementation.
            site (Site, optional):  Site object. Not used in this
                                    implementation.

        Returns:
            list: A list of option dictionaries containing "id" and "text".
        """
        optionset = []
        if search is None:
            return optionset

        for _n, instrument in self.get_all_instruments().items():
            for key, value in instrument["Instrument"].items():
                if re.search(search, value, flags=re.IGNORECASE):
                    optionset.append(
                        {
                            "id": f"{self.id_prefix}:{instrument['Instrument']['id']}",
                            "text": f"{self.text_prefix} {instrument['Instrument']['code']}",
                        }
                    )
                    break
        return optionset[: self.max_hits]
