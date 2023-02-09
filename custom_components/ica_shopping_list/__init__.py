"""This is a script that provides support for managing a shopping list in the Home Assistant platform."""
import asyncio
import logging
import uuid
import requests
import json
import secrets
import aiohttp

import voluptuous as vol #It uses the voluptuous library to provide validation of the configuration options passed to the script

#from homeassistant.const import HTTP_NOT_FOUND, HTTP_BAD_REQUEST
from homeassistant.core import callback
from homeassistant.components import http
from homeassistant.components.http.data_validator import RequestDataValidator
from homeassistant.helpers import intent
import homeassistant.helpers.config_validation as cv
from homeassistant.util.json import load_json, save_json
from homeassistant.components import websocket_api
from homeassistant.const import (CONF_PASSWORD, CONF_USERNAME)

# Above it imports the asyncio, logging, uuid, requests, json, and secrets libraries. It also imports various modules from the homeassistant package such as const, core, components, helpers and util.

ATTR_NAME = "name"  #Defines the constant ATTR_NAME.

DOMAIN = "ica_shopping_list" #Defines the constant DOMAIN.
_LOGGER = logging.getLogger(__name__) #Defines the constant LOGGER.
CONFIG_SCHEMA = vol.Schema({ #Defines the constant CONFIG_SCHEMA.
  DOMAIN: {
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
  },
}, extra=vol.ALLOW_EXTRA)

#The following defines variables to store credentials and the shoppinglist.
icaUser = None
icaPassword = None
icaList = None

#Here it also defines various event, intent, and schema constants such as EVENT, INTENT_ADD_ITEM, INTENT_LAST_ITEMS, ITEM_UPDATE_SCHEMA, etc. which are used to handle different actions and events related to the shopping list.
EVENT = "shopping_list_updated"
INTENT_ADD_ITEM = "HassShoppingListAddItem"
INTENT_LAST_ITEMS = "HassShoppingListLastItems"
ITEM_UPDATE_SCHEMA = vol.Schema({"complete": bool, ATTR_NAME: str})
PERSISTENCE = ".shopping_list.json"

#It also defines various service constants such as SERVICE_ADD_ITEM, SERVICE_COMPLETE_ITEM, etc. which are used to handle different actions related to the shopping list.
SERVICE_ADD_ITEM = "add_item"
SERVICE_COMPLETE_ITEM = "complete_item"

SERVICE_ITEM_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): vol.Any(None, cv.string)})

#It also defines various websocket constants such as WS_TYPE_SHOPPING_LIST_ITEMS, WS_TYPE_SHOPPING_LIST_ADD_ITEM, WS_TYPE_SHOPPING_LIST_UPDATE_ITEM, etc. which are used to handle different websocket events related to the shopping list.
WS_TYPE_SHOPPING_LIST_ITEMS = "shopping_list/items"
WS_TYPE_SHOPPING_LIST_ADD_ITEM = "shopping_list/items/add"
WS_TYPE_SHOPPING_LIST_UPDATE_ITEM = "shopping_list/items/update"
WS_TYPE_SHOPPING_LIST_CLEAR_ITEMS = "shopping_list/items/clear"

#It also defines various schema constants such as SCHEMA_WEBSOCKET_ITEMS, SCHEMA_WEBSOCKET_ADD_ITEM, SCHEMA_WEBSOCKET_UPDATE_ITEM, etc. which are used to validate the incoming data for different websocket events.
SCHEMA_WEBSOCKET_ITEMS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_SHOPPING_LIST_ITEMS}
)

SCHEMA_WEBSOCKET_ADD_ITEM = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_SHOPPING_LIST_ADD_ITEM, vol.Required("name"): str}
)

SCHEMA_WEBSOCKET_UPDATE_ITEM = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SHOPPING_LIST_UPDATE_ITEM,
        vol.Required("item_id"): str,
        vol.Optional("name"): str,
        vol.Optional("complete"): bool,
    }
)

SCHEMA_WEBSOCKET_CLEAR_ITEMS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_SHOPPING_LIST_CLEAR_ITEMS}
)
""" Overall, the above script is responsible for providing support for managing a shopping list in the Home Assistant platform by validating the configuration options, handling different events and actions related to the shopping list, and handling websocket events related to the shopping list."""



#The following is an async_setup function that is responsible for setting up the shopping list feature when the script is loaded by the Home Assistant platform.
#It first declares three global variables icaUser, icaPassword, icaList and assigns them the values of the username, password, and listname keys in the config dictionary respectively.
#It then registers several services that can be called by the Home Assistant platform to perform actions related to the shopping list, such as adding or completing an item in the list. It also registers several views that can handle HTTP requests related to the shopping list.
#It also registers the #####built-in panel for the shopping list in the Home Assistant frontend##### and registers various commands that can be called via websockets to handle different actions related to the shopping list.
#It also has a commented out line that appears to be trying to authenticate the user with the Connect.authenticate(icaUser, icaPassword) method, but it is not clear from the code snippet provided what the Connect object is or how it is used.
#At the end of the function, it returns True to indicate that the setup was successful.
@asyncio.coroutine
def async_setup(hass, config):
    """Initialize the shopping list."""
    global icaUser
    icaUser = config["ica_shopping_list"]["username"]
    global icaPassword
    icaPassword = config["ica_shopping_list"]["password"]
    global icaList
    icaList = config["ica_shopping_list"]["listname"]
    _LOGGER.debug(config)

    @asyncio.coroutine
    def add_item_service(call):
        """Add an item with `name`."""
        data = hass.data[DOMAIN]
        name = call.data.get(ATTR_NAME)
        if name is not None:
            data.async_add(name)

    @asyncio.coroutine
    def complete_item_service(call):
        """Mark the item provided via `name` as completed."""
        data = hass.data[DOMAIN]
        name = call.data.get(ATTR_NAME)
        if name is None:
            return
        try:
            item = [item for item in data.items if item["name"] == name][0]
        except IndexError:
            _LOGGER.error("Removing of item failed: %s cannot be found", name)
        else:
            data.async_update(item["id"], {"name": name, "complete": True})

    data = hass.data[DOMAIN] = ShoppingData(hass)
    yield from data.async_load()

    intent.async_register(hass, AddItemIntent())
    intent.async_register(hass, ListTopItemsIntent())

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_ITEM, add_item_service, schema=SERVICE_ITEM_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE_ITEM, complete_item_service, schema=SERVICE_ITEM_SCHEMA
    )

    hass.http.register_view(ShoppingListView)
    hass.http.register_view(CreateShoppingListItemView)
    hass.http.register_view(UpdateShoppingListItemView)
    hass.http.register_view(ClearCompletedItemsView)

    hass.components.websocket_api.async_register_command(
        WS_TYPE_SHOPPING_LIST_ITEMS, websocket_handle_items, SCHEMA_WEBSOCKET_ITEMS
    )
    hass.components.websocket_api.async_register_command(
        WS_TYPE_SHOPPING_LIST_ADD_ITEM, websocket_handle_add, SCHEMA_WEBSOCKET_ADD_ITEM
    )
    hass.components.websocket_api.async_register_command(
        WS_TYPE_SHOPPING_LIST_UPDATE_ITEM,
        websocket_handle_update,
        SCHEMA_WEBSOCKET_UPDATE_ITEM,
    )
    hass.components.websocket_api.async_register_command(
        WS_TYPE_SHOPPING_LIST_CLEAR_ITEMS,
        websocket_handle_clear,
        SCHEMA_WEBSOCKET_CLEAR_ITEMS,
    )

    #Connect.authenticate(icaUser, icaPassword)

    return True



#The following code defines a new class called ShoppingData which is responsible for holding and manipulating the shopping list data. The class has several methods, including async_add, async_update, async_clear_completed, and async_load.
class ShoppingData:
    """Class to hold shopping list data."""

    def __init__(self, hass):
        """Initialize the shopping list."""
        self.hass = hass
        self.items = []

    #The async_add method takes in a name as a parameter and adds it to the shopping list by calling an API using the Connect class's post_request method.
    @callback
    async def async_add(self, name):
        """Add a shopping list item."""
        self.items = []
        item = json.dumps({"CreatedRows":[{"IsStrikedOver": "false", "ProductName": name}]})
        _LOGGER.debug("Item: " + str(item))
        URI = "/api/user/offlineshoppinglists"
        #api_data = Connect.post_request(URI, item)
        api_data = await hass.async_add_executor_job(Connect.post_request, URI, item)
        _LOGGER.debug("Adding product: " + str(item))
        for row in api_data["Rows"]:
            name = row["ProductName"].capitalize()
            uuid = row["OfflineId"]
            complete = row["IsStrikedOver"]

            item = {"name": name, "id": uuid, "complete": complete}
            _LOGGER.debug("Item: " + str(item))
            self.items.append(item)

        _LOGGER.debug("Items: " + str(self.items))
        return self.items

    #The async_update method takes in an item ID and information (info) as parameters. It updates a shopping list item by calling an API using the Connect class's post_request method.
    @callback
    async def async_update(self, item_id, info):
        """Update a shopping list item."""

        _LOGGER.debug("Info: " + str(info))
        self.items = []

        if info.get("complete") == True or info.get("complete") == False:
            item = {"ChangedRows": [{"OfflineId": item_id, "IsStrikedOver": info.get("complete")}]}
        elif info.get("name"):
            item = {"ChangedRows": [{"OfflineId": item_id, "ProductName": info.get("name")}]}
        _LOGGER.debug("Item: " + str(item))

        URI = "/api/user/offlineshoppinglists"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(URI, json=item) as resp:
                    api_data = await resp.json()
            except Exception as e:
                _LOGGER.error("Error occured while updating the item: %s", e)

        _LOGGER.debug("Updating product: " + str(item))
        for row in api_data["Rows"]:
            name = row["ProductName"].capitalize()
            uuid = row["OfflineId"]
            complete = row["IsStrikedOver"]

            item = {"name": name, "id": uuid, "complete": complete}
            _LOGGER.debug("Item: " + str(item))
            self.items.append(item)

        _LOGGER.debug("Items: " + str(self.items))
        return self.items

    #The async_clear_completed method clears completed items by deleting them from the shopping list by calling an API using the Connect class's post_request method.
    @callback
    def async_clear_completed(self, hass):
        """Clear completed items."""
        completed_items = []

        for c_item in self.items:
            if c_item["complete"] == True:
                completed_items.append(c_item["id"])
        _LOGGER.debug("Items to delete: " + str(completed_items))

        self.items = []
        item = json.dumps({ "DeletedRows": completed_items })
        _LOGGER.debug("Item: " + str(item))

        URI = "/api/user/offlineshoppinglists"
        api_data = Connect.post_request(URI, item)
        _LOGGER.debug("Adding product: " + str(api_data))
        for row in api_data["Rows"]:
            name = row["ProductName"].capitalize()
            uuid = row["OfflineId"]
            complete = row["IsStrikedOver"]

            item = {"name": name, "id": uuid, "complete": complete}
            _LOGGER.debug("Item: " + str(item))
            self.items.append(item)

        _LOGGER.debug("Items: " + str(self.items))
        return self.items

    #The async_load method loads the items by calling an API using the Connect class's get_request method and populating the self.items list with the data returned from the API.
    @asyncio.coroutine
    def async_load(self):
        """Load items."""

        def load():
            """Load the items synchronously."""
            URI = "/api/user/offlineshoppinglists"
            api_data = Connect.get_request(URI)
            _LOGGER.debug("Adding to ica: " + str(api_data))
            for row in api_data["Rows"]:
                name = row["ProductName"].capitalize()
                uuid = row["OfflineId"]
                complete = row["IsStrikedOver"]

                item = {"name": name, "id": uuid, "complete": complete}
                _LOGGER.debug("Item: " + str(item))
                self.items.append(item)

            _LOGGER.debug("Items: " + str(self.items))
            return self.items
#            return load_json(self.hass.config.path(PERSISTENCE), default=[])

        self.items = yield from self.hass.async_add_job(load)

    def save(self):
        """Save the items."""
        save_json(self.hass.config.path(PERSISTENCE), self.items)



#The following code defines a new class called "AddItemIntent" which is derived from the "intent.IntentHandler" class. This class is used to handle the "AddItem" intent, which allows the user to add an item to their shopping list. The class defines a single method called "async_handle" which is called when the intent is invoked.
#The method takes an "intent_obj" as an input, which contains information about the intent such as the slots (parameters) passed by the user. The method starts by validating the slots and extracting the "item" slot from the intent_obj. Then it calls the async_add function of the ShoppingData class passing the item name.
#Finally, the method creates a response object, sets the speech output and fires an event. The response object is returned to the user, which contains the speech output and any other information that was set.
class AddItemIntent(intent.IntentHandler):
    """Handle AddItem intents."""

    intent_type = INTENT_ADD_ITEM
    slot_schema = {"item": cv.string}

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        slots = self.async_validate_slots(intent_obj.slots)
        item = slots["item"]["value"]
        intent_obj.hass.data[DOMAIN].async_add(item)

        response = intent_obj.create_response()
        response.async_set_speech(f"I've added {item} to your shopping list")
        intent_obj.hass.bus.async_fire(EVENT)
        return response



#The following code defines a new class called ListTopItemsIntent that is an intent handler for the INTENT_LAST_ITEMS intent type. This class will handle the intent by retrieving the last 5 items from the shopping list and creating a response that includes these items in a list. 
#If the shopping list is empty, the response will indicate that there are no items on the list. The response is then returned. This code assumes that there is an INTENT_LAST_ITEMS variable that is already defined and that the items attribute of the ShoppingData class is a list of items that is being updated by the other functions in your code.
class ListTopItemsIntent(intent.IntentHandler):
    """Handle AddItem intents."""

    intent_type = INTENT_LAST_ITEMS
    slot_schema = {"item": cv.string}

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        items = intent_obj.hass.data[DOMAIN].items[-5:]
        response = intent_obj.create_response()

        if not items:
            response.async_set_speech("There are no items on your shopping list")
        else:
            response.async_set_speech(
                "These are the top {} items on your shopping list: {}".format(
                    min(len(items), 5),
                    ", ".join(itm["name"] for itm in reversed(items)),
                )
            )
        return response



#The following code This code creates a new Home Assistant view, accessible at the URL "/api/shopping_list"(See Shopping List in side bar), that retrieves and returns the current items in the shopping list. The view is named "api:shopping_list" and when a GET request is made to this endpoint, it will return the items stored in the "hass.data[DOMAIN].items" object in JSON format. This allows other parts of your system or external clients to access the shopping list data through this API endpoint.
class ShoppingListView(http.HomeAssistantView):
    """View to retrieve shopping list content."""

    url = "/api/shopping_list"
    name = "api:shopping_list"

    @callback
    def get(self, request):
        """Retrieve shopping list items."""
        return self.json(request.app["hass"].data[DOMAIN].items)



#This code defines a new view that can be accessed via the HTTP API of Home Assistant. The view is accessible at the endpoint '/api/shopping_list/item/{item_id}' and is designed to handle POST requests.
#When the endpoint is accessed, the view will attempt to update a shopping list item by calling the 'async_update' method on the 'ShoppingData' object with the provided item_id and the data provided in the request body. If the update is successful, it will fire an event and return the updated item as a JSON object. If there is an error, such as the item not being found or the data being invalid, it will return an appropriate message and HTTP status code.
class UpdateShoppingListItemView(http.HomeAssistantView):
    """View to retrieve shopping list content."""

    url = "/api/shopping_list/item/{item_id}"
    name = "api:shopping_list:item:id"

    async def post(self, request, item_id):
        """Update a shopping list item."""
        data = await request.json()

        try:
            item = request.app["hass"].data[DOMAIN].async_update(item_id, data)
            request.app["hass"].bus.async_fire(EVENT)
            return self.json(item)
        except KeyError:
            return self.json_message("Item not found", 404)
        except vol.Invalid:
            return self.json_message("Item not found", 400)



#This code defines a new class called CreateShoppingListItemView, which is a subclass of http.HomeAssistantView. This class creates a new endpoint at the URL "/api/shopping_list/item" that accepts POST requests. When a POST request is made to this endpoint, the post method of the class will be called.
#The post method uses the RequestDataValidator decorator to validate the incoming JSON data against a schema that requires a single field called "name", which must be a string. If the incoming data is not valid, a HTTPBadRequest response will be returned.
#The post method then calls the async_add method on the ShoppingData instance stored in hass.data[DOMAIN] with the value of the "name" field from the incoming JSON as the argument. This will add the item to the shopping list.
#Then it fires an event "EVENT" and returns the response in json format containing the item, which was just added.
class CreateShoppingListItemView(http.HomeAssistantView):
    """View to retrieve shopping list content."""

    url = "/api/shopping_list/item"
    name = "api:shopping_list:item"

    @RequestDataValidator(vol.Schema({vol.Required("name"): str}))
    @asyncio.coroutine
    def post(self, request, data):
        """Create a new shopping list item."""
        item = request.app["hass"].data[DOMAIN].async_add(data["name"])
        request.app["hass"].bus.async_fire(EVENT)
        return self.json(item)



#This code defines a new class ClearCompletedItemsView, which is a subclass of http.HomeAssistantView. The class has a single method post() which allows the user to clear all the completed items in the shopping list by sending a post request to the specified endpoint "/api/shopping_list/clear_completed". When the endpoint is hit, the post() method is executed and it calls the async_clear_completed() method from the ShoppingData class which removes all the completed items from the shopping list and then it fires an event EVENT to notify any listening component that the list has been updated. Finally, it returns a json message "Cleared completed items." to the client.
class ClearCompletedItemsView(http.HomeAssistantView):
    """View to retrieve shopping list content."""

    url = "/api/shopping_list/clear_completed"
    name = "api:shopping_list:clear_completed"

    @callback
    def post(self, request):
        """Retrieve if API is running."""
        hass = request.app["hass"]
        hass.data[DOMAIN].async_clear_completed()
        hass.bus.async_fire(EVENT)
        return self.json_message("Cleared completed items.")



#This code defines a websocket_handle_items() function, which is a callback function that handles incoming WebSocket messages for getting the items on the shopping list. The function takes three arguments: hass, connection, and msg.
#hass is an instance of the Home Assistant object that represents the running instance of the Home Assistant platform. connection is an instance of a WebSocket connection, and msg is the message received via the WebSocket connection.
#The function uses the hass.data[DOMAIN].items attribute to retrieve the items on the shopping list, and then sends a message back to the client via the WebSocket connection using the connection.send_message() method. The message sent is a result message containing the items on the shopping list.
#This function would typically be used in conjuction with the websocket_api library and registered to handle a specific type of message. So when client will send a message with a specific type, this function will be called to handle that message.
@callback
def websocket_handle_items(hass, connection, msg):
    """Handle get shopping_list items."""
    connection.send_message(
        websocket_api.result_message(msg["id"], hass.data[DOMAIN].items)
    )



#is a function definition for a function called "websocket_handle_add", which appears to handle a message received via a websocket connection to add an item to a shopping list. The function takes three parameters:
# 1. "hass": an object representing the Home Assistant instance
# 2. "connection": an object representing the websocket connection
# 3. msg": a dictionary containing the message received via the websocket connection.
#The function uses the "async_add" method from the shopping list data object to add an item to the list, with the name of the item taken from the "msg" dictionary. Then it fires the "EVENT" and sends the result of the "async_add" method back to the client via the websocket connection.
#@callback
#def websocket_handle_add(hass, connection, msg):
#    """Handle add item to shopping_list."""
#    item = hass.data[DOMAIN].async_add(msg["name"])
#    hass.bus.async_fire(EVENT)
#    connection.send_message(websocket_api.result_message(msg["id"], item))

@callback
async def websocket_handle_add(hass, connection, msg):
    """Handle add command."""
    if "name" not in msg:
        return "Error: The 'name' key is missing in the message"
    item = await hass.data[DOMAIN].async_add(msg["name"])
    connection.send_message(websocket_api.result_message(msg["id"], item))



#This code defines an asynchronous function websocket_handle_update, which is intended to handle an update request for a shopping list item via a WebSocket connection. The function takes three parameters: hass, connection, and msg, which represent the Home Assistant instance, the WebSocket connection object, and the WebSocket message, respectively.
#The function first extracts the message id (msg_id) and the item id (item_id) from the message, and removes the type key from the message. The remaining data is stored in the data variable.
#Then, the function attempts to update the item using the async_update method of the ShoppingData class, passing it the item_id and the data. If the item is successfully updated, the function sends a message through the WebSocket connection containing the updated item data. If an error occurs, such as the item not being found, the function sends a message through the WebSocket connection containing an error message with the error details.
@websocket_api.async_response
async def websocket_handle_update(hass, connection, msg):
    """Handle update shopping_list item."""
    msg_id = msg.pop("id")
    item_id = msg.pop("item_id")
    msg.pop("type")
    data = msg

    try:
        item = hass.data[DOMAIN].async_update(item_id, data)
        hass.bus.async_fire(EVENT)
        connection.send_message(websocket_api.result_message(msg_id, item))
    except KeyError:
        connection.send_message(
            websocket_api.error_message(msg_id, "item_not_found", "Item not found")
        )



#This code is defining a new WebSocket API handle function called websocket_handle_clear. This function is intended to be used as a callback function that will be called when the client sends a WebSocket message of type "clear" to the server.
#The function takes three arguments: hass, connection and msg. hass is the Home Assistant object, connection is the WebSocket connection object and msg is the message sent by the client.
#The function first calls the async_clear_completed method on the hass.data[DOMAIN] object, which is expected to be an instance of the ShoppingData class, which clears all completed items from the shopping list. Then the function triggers an event EVENT and sends the response message to the client with the id of the message.
@callback
def websocket_handle_clear(hass, connection, msg):
    """Handle clearing shopping_list items."""
    hass.data[DOMAIN].async_clear_completed()
    hass.bus.async_fire(EVENT)
    connection.send_message(websocket_api.result_message(msg["id"]))




#The following is a class called Connect, which appears to be handling the authentication and communication with the ICA shopping list API. The class has several static methods such as get_request, post_request, authenticate etc.
#The authenticate method is used to get an authentication ticket and list id from the ICA API. It uses the icaUser, icaPassword, and icaList global variables that are set in the async_setup function.
#The get_request and post_request methods are used to make GET and POST requests to the ICA API respectively. These methods add the authentication ticket and list id to the headers of the request and handle the case of the authentication ticket expiring.
#It also have some global variable getters such as glob_user, glob_password and glob_list. It will return the value of the global variable which is set in async_setup method.
#Overall, this class is responsible for handling the authentication and communication with the ICA shopping list API and it appears to be used by other parts of the script to interact with the API.
class Connect:

    AUTHTICKET = None
    listId = None

    def glob_user():
        global icaUser
        return icaUser

    def glob_password():
        global icaPassword
        return icaPassword

    def glob_list():
        global icaList
        return icaList

    @staticmethod
    def get_request(uri):
        """Do API request."""
        if Connect.AUTHTICKET is None:
            renewTicket = Connect.authenticate()
            Connect.AUTHTICKET = renewTicket["authTicket"]
            Connect.listId = renewTicket["listId"]

        url = "https://handla.api.ica.se" + uri + "/" + Connect.listId
        headers = {"Content-Type": "application/json", "AuthenticationTicket": Connect.AUTHTICKET}
        req = requests.get(url, headers=headers)

        if req.status_code == 401:
            _LOGGER.debug("API key expired. Aquire new")

            renewTicket = Connect.authenticate()
            Connect.AUTHTICKET = renewTicket["authTicket"]
            Connect.listId = renewTicket["listId"]
            
            headers = {"Content-Type": "application/json", "AuthenticationTicket": Connect.AUTHTICKET}
            req = requests.get(url, headers=headers)

            if req.status_code != requests.codes.ok:
                _LOGGER.exception("API request returned error %d", req.status_code)

            else:
                _LOGGER.debug("API request returned OK %d", req.text)

                json_data = json.loads(req.content)
                return json_data

        elif req.status_code != requests.codes.ok:
            _LOGGER.exception("API request returned error %d", req.status_code)
        else:
            _LOGGER.debug("API request returned OK %d", req.text)

        json_data = json.loads(req.content)
        return json_data

    @staticmethod
    def post_request(uri, data):
        """Do API request."""
        if Connect.AUTHTICKET is None:
            renewTicket = Connect.authenticate()
            Connect.AUTHTICKET = renewTicket["authTicket"]
            Connect.listId = renewTicket["listId"]

        url = "https://handla.api.ica.se" + uri + "/" + Connect.listId + "/sync"
        _LOGGER.debug("URL: " + url)
        headers = {"Content-Type": "application/json", "AuthenticationTicket": Connect.AUTHTICKET}
        req = requests.post(url, headers=headers, data=data)

        if req.status_code == 401:
            _LOGGER.debug("API key expired. Aquire new")

            renewTicket = Connect.authenticate()
            Connect.AUTHTICKET = renewTicket["authTicket"]
            Connect.listId = renewTicket["listId"]
            
            headers = {"Content-Type": "application/json", "AuthenticationTicket": Connect.AUTHTICKET}
            req = requests.post(url, headers=headers)

            if req.status_code != requests.codes.ok:
                _LOGGER.exception("API request returned error %d", req.status_code)

            else:
                _LOGGER.debug("API request returned OK %d", req.text)

                json_data = json.loads(req.content)
                return json_data

        elif req.status_code != requests.codes.ok:
            _LOGGER.exception("API request returned error %d", req.status_code)
        else:
            _LOGGER.debug("API request returned OK %d", req.text)

        json_data = json.loads(req.content)
        return json_data

    @staticmethod
    def authenticate():
        """Do API request"""

        icaUser = Connect.glob_user()
        icaPassword = Connect.glob_password()
        icaList = Connect.glob_list()
        listId = None

        url = "https://handla.api.ica.se/api/login"
        req = requests.get(url, auth=(str(icaUser), str(icaPassword)))

        if req.status_code != requests.codes.ok:
            _LOGGER.exception("API request returned error %d", req.status_code)
        else:
            _LOGGER.debug("API request returned OK %d", req.text)
            authTick = req.headers["AuthenticationTicket"]

            if Connect.listId is None:
                url = 'https://handla.api.ica.se/api/user/offlineshoppinglists'
                headers = {"Content-Type": "application/json", "AuthenticationTicket": authTick}
                req = requests.get(url, headers=headers)
                response = json.loads(req.content)

                for lists in response["ShoppingLists"]:
                    if lists["Title"] == icaList:
                        listId = lists["OfflineId"]
            
                if Connect.listId is None and listId is None:
                    _LOGGER.info("Shopping-list not found: %s", icaList)
                    newOfflineId = secrets.token_hex(4) + "-" + secrets.token_hex(2) + "-" + secrets.token_hex(2) + "-"
                    newOfflineId = newOfflineId + secrets.token_hex(2) + "-" + secrets.token_hex(6)
                    _LOGGER.debug("New hex-string: %s", newOfflineId)
                    data = json.dumps({"OfflineId": newOfflineId, "Title": icaList, "SortingStore": 0})

                    url = 'https://handla.api.ica.se/api/user/offlineshoppinglists'
                    headers = {"Content-Type": "application/json", "AuthenticationTicket": authTick}
                    
                    _LOGGER.debug("List does not exist. Creating %s", icaList)
                    req = requests.post(url, headers=headers, data=data)

                    if req.status_code == 200:
                        url = 'https://handla.api.ica.se/api/user/offlineshoppinglists'
                        headers = {"Content-Type": "application/json", "AuthenticationTicket": authTick}
                        req = requests.get(url, headers=headers)
                        response = json.loads(req.content)

                        _LOGGER.debug(response)

                        for lists in response["ShoppingLists"]:
                            if lists["Title"] == icaList:
                                listId = lists["OfflineId"]
                                _LOGGER.debug(icaList + " created with offlineId %s", listId)

            authResult = {"authTicket": authTick, "listId": listId}
            return authResult
