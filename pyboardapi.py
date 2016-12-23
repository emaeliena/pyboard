import logging
import os

from bottle import route, run, error, response, install, request
from bson.objectid import ObjectId
from bson import json_util

from bottle.ext.mongo import MongoPlugin


logging.basicConfig(level=logging.DEBUG)

API_PORT = os.getenv('API_PORT', 8000)

MONGO_SERVER_ADDRESS = os.getenv('MONGO_SERVER_ADDRESS', '127.0.0.1')
MONGO_SERVER_PORT = os.getenv('MONGO_SERVER_PORT', 27017)

MIME_JSON = 'application/json'

mongo_plugin = MongoPlugin('mongodb://{}:{}'.format(MONGO_SERVER_ADDRESS, MONGO_SERVER_PORT), 'bg', json_mongo=True)
install(mongo_plugin)


class JoinCommand:

    code = 'join'

    def __init__(self, name):
        self.name = name

    @property
    def doc(self):
        return {'command': self.code, 'name': self.name}


class SplendorPlugin:

    short_name = 'splendor'

    def create_game_doc(self):
        return {'plugin': self.short_name, 'commands': []}

    def extend_commands_factory(self, factory):
        factory[JoinCommand.code] = JoinCommand


class PluginFactory(dict):

    def __init__(self, *args, **kwargs):
        super(PluginFactory, self).__init__(*args, **kwargs)
        self._init_plugin(SplendorPlugin())

    def _init_plugin(self, plugin):
        self[plugin.short_name] = plugin

    def get(self, key, **kwargs):
        if key not in self:
            raise KeyError(key)
        return self[key]

plugin_factory = PluginFactory()


class CommandsFactory(dict):

    def __init__(self, *args, **kwargs):
        super(CommandsFactory, self).__init__(*args, **kwargs)

    def get(self, key, **kwargs):
        if key not in self:
            raise KeyError(key)
        return self[key]

    def create(self, **kwargs):
        command_class = self.get(kwargs['command'])
        command_params = {key: value for key, value in kwargs.items() if key != 'command'}
        command = command_class(**command_params)
        return command


class Manager:

    def __init__(self, model):
        self.model = model

    @property
    def collection(self):
        return mongo_plugin.get_mongo()[self.model.collection]

    def all(self, projection=None):
        return self.collection.find(projection=projection)

    def get_by_pk(self, pk):
        return self.collection.find_one({'_id': ObjectId(pk)})


class Game:

    collection = 'games'

    def __init__(self, plugin):
        self.plugin = plugin

Game.objects = Manager(Game)


@route('/v1/games')
def list_games():
    response.content_type = MIME_JSON
    return json_util.dumps({'games': Game.objects.all(projection={'commands': False})})


@route('/v1/games/<game_id>')
def game_details(game_id):
    response.content_type = MIME_JSON
    return json_util.dumps({'game': Game.objects.get_by_pk(ObjectId(game_id))})


@route('/v1/games', method='PUT')
def create_game(mongodb):
    try:
        plugin_name = request.json.get('plugin')
        plugin = plugin_factory.get(plugin_name)
        game_doc = plugin.create_game_doc()
        result = mongodb.games.insert_one(game_doc)
        status = {'game': {'$oid': result.inserted_id}}
    except Exception:
        status = {'ok': False}
    response.content_type = MIME_JSON
    return json_util.dumps(status)


@route('/v1/games/<game_id>', method='DELETE')
def delete_game(game_id, mongodb):
    result = mongodb.games.delete_one({'_id': ObjectId(game_id)})
    return {'ok': result.deleted_count == 1}


@route('/v1/games/<game_id>/commands', method='PUT')
def create_command(game_id, mongodb):
    game = Game.objects.get_by_pk(game_id)
    plugin = plugin_factory.get(game['plugin'])
    commands_factory = CommandsFactory()
    plugin.extend_commands_factory(commands_factory)
    command = commands_factory.create(**request.json)
    result = mongodb.games.update_one({'_id': game['_id']}, {'$push': {'commands': command.doc}})
    return {'ok': result.modified_count == 1}


@error(404)
def error404(error_data):
    return str(error_data)

if __name__ == '__main__':
    run(host='0.0.0.0', port=API_PORT, debug=True)
