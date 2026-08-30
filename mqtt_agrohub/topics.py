"""Parseo de tópicos ahub/<device_id>/<resto> — ver docs/TOPICS.md."""
from collections import namedtuple

TopicAgrohub = namedtuple('TopicAgrohub', ['device_id', 'base_topic', 'subtopico'])


def parsear(topic):
    """'ahub/device0001/data' -> TopicAgrohub('device0001', 'ahub/device0001', 'data').
    Devuelve None si el tópico no tiene la forma ahub/<device_id>/<algo>."""
    partes = topic.split('/')
    if len(partes) < 3 or partes[0] != 'ahub':
        return None
    device_id = partes[1]
    subtopico = '/'.join(partes[2:])
    return TopicAgrohub(device_id=device_id, base_topic=f'ahub/{device_id}', subtopico=subtopico)


def topic_control_valvulas(device_id):
    return f'ahub/{device_id}/control/valvulas'
