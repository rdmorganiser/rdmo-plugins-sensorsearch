import logging

from rdmo_sensorsearch.client import fetch_json
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
    # max_hits = 10 from base provider

    id_prefix = "gfzgipp"
    text_prefix = "GIPP:"
    base_url = "https://gipp.gfz-potsdam.de/instruments"
    instruments_url = "{base_url}/index.json?limit=10000&program=MOSES"

    option_id = "{prefix}:{id}"
    option_text = "{prefix} {code}"


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
        if not search:
            return []

        url = self.instruments_url.format(base_url=self.base_url)
        instruments = fetch_json(url)

        if not instruments:
            logger.debug("No instruments found for query '%s'", search)
            return []

        optionset = []
        for instrument in instruments:
            option = self.extract_option_for_instrument(instrument, search)
            if option:
                optionset.append(option)
            if len(optionset) >= self.max_hits:
                break

        return optionset


    def extract_option_for_instrument(self, instrument: dict, search: str) -> dict | None:
        try:
            inst_data = instrument["Instrument"]
            if not isinstance(inst_data, dict):
                return None

            query = search.lower()
            for _, value in inst_data.items():
                if query in str(value).lower():
                    return {
                        "id": self.option_id.format(prefix=self.id_prefix, id=inst_data["id"]),
                        "text": self.option_text.format(prefix=self.text_prefix, code=inst_data["code"]),
                    }
        except (KeyError, TypeError) as e:
            logger.debug("Skipping malformed instrument entry: %s", e)

        return None
