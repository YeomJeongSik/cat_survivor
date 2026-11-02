"""Allowed state graphs, enforced by transitions rather than direct assignments."""
from transitions import Machine


CAT_ACTIVE = ('IDLE','MOVE','JUMP','FALL','DASH','ATTACK','HIT','GROOM')
ENEMY_GRAPHS = {
    'magpie': {'IDLE':('FLY',), 'FLY':('WARNING',), 'WARNING':('DIVE','RUSH'),
               'DIVE':('IDLE',), 'RUSH':('RECOVER',), 'RECOVER':('IDLE',)},
    'squirrel': {'IDLE':('PATROL',), 'PATROL':('CROUCH_CHARGE',),
                 'CROUCH_CHARGE':('JUMP',), 'JUMP':('LAND',), 'LAND':('PATROL',)},
    'bee': {'IDLE':('TARGET_LOCK',), 'TARGET_LOCK':('DASH',), 'DASH':('WAIT',),
            'WAIT':('TARGET_LOCK',)},
    'snake': {'IDLE':('BURROW_MOVE','CHARGE'), 'BURROW_MOVE':('CHARGE',),
              'CHARGE':('POP_UP',), 'POP_UP':('RETURN_UNDERGROUND',),
              'RETURN_UNDERGROUND':('IDLE',)},
}


def actor_machine(actor, graph):
    states = list(graph)
    if actor.state not in states:
        raise ValueError(f'Invalid {type(actor).__name__} initial state: {actor.state}')
    edges = [dict(trigger='enter_'+dest,source=source,dest=dest)
             for source, targets in graph.items() for dest in (source,*targets)]
    return Machine(model=actor,states=states,transitions=edges,initial=actor.state,
                   auto_transitions=False,send_event=True,after_state_change='_state_entered')
