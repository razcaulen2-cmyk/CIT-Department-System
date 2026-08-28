import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models import event_model


def main(event_id=None):
    events = event_model.get_all_events()
    if not events:
        print('No events found.')
        return

    target = None
    if event_id:
        for ev in events:
            if str(ev.get('id')) == str(event_id):
                target = ev
                break
        if not target:
            print(f'Event id {event_id} not found.')
            return
    else:
        target = events[0]

    print('Target event: ', target.get('id'), '-', target.get('name'), target.get('date'))
    print('Clearing existing fines for event...')
    event_model.clear_fines_for_event(target.get('id'))
    print('Cleared fines.')
    print('Re-syncing fines for event...')
    event_model.sync_fines_for_event(target)
    print('Resync complete.')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Clear and resync fines for an event')
    p.add_argument('--event-id', help='Event ID to resync (optional). If omitted, uses most recent event')
    args = p.parse_args()
    main(args.event_id)
