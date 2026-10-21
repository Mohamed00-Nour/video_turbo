"""Structured AI walkthroughs rendered locally; never desktop capture or AI-authored code."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
import subprocess

from ai_generation import object_schema
import pc_tips_ai
from pipeline_common import fingerprint, read_cache, write_json

ENGINE = Path(__file__).resolve().parent
SURFACES = ('settings', 'explorer', 'clipboard', 'notepad', 'desktop', 'start', 'task_manager', 'control_panel', 'windows')
WINDOW_ACTIONS = ('activate_window', 'snap_left', 'snap_right', 'calculate')
ACTIONS = ('select', 'toggle_on', 'toggle_off', 'shortcut', 'result', 'context_menu', 'choose', *WINDOW_ACTIONS)
CAPABILITIES = (
    'Animated mode can show Settings, Explorer, Clipboard, Notepad, Desktop, Start, Task Manager and Control Panel '
    'using rows, selection, toggles, dropdowns, shortcuts and context menus. It can also show two actual windows '
    '(Notepad and Calculator), overlapping, activating either window, snapping left/right with Win+Arrow, '
    'dismissing Snap Assist with Esc, and typing a simple nonnegative integer addition in Calculator. '
    'Window actions are limited to activate_window, snap_left, snap_right, calculate and a static result hold. '
    'Both windows stay open and visible: minimizing, restoring, closing, launching and hiding windows are unsupported. '
    'Task Manager rows are illustrative UI, not measured CPU, memory or timing data. '
    'Never fabricate resource readings, benchmarks or speed gains; an app disappearing does not prove lower resource use. '
    'It can show actual acrylic transparency on the Start menu and taskbar, switch Transparency effects off '
    'in Windows 10 Settings > Personalization > Colors, and reopen the same Start menu with solid backgrounds. '
    'This demonstrates removal of a documented GPU-intensive visual effect, not a measured speed/resource improvement. '
    'Choose a tip whose problem, every action and final result can be demonstrated with these capabilities. '
    'Do not substitute rows or explanatory notes for unsupported visual effects or applications. '
)
PERFORMANCE_TOPIC = 'windows10-disable-transparency-effects'
PERFORMANCE_GUIDANCE = (
    'For an animated performance episode, use the supported technique windows10-disable-transparency-effects. '
    'Show a Windows 10 dark-mode Start menu with acrylic transparency initially On. '
    'The observable symptom is an unwanted translucent/blurred effect, not invented slowness, stutter or a broken PC. '
    'Open Settings > Personalization > Colors and turn Transparency effects Off if it is enabled. '
    'Reopen Start with the exact same Ctrl+Esc action, app list and desktop wallpaper, now with a solid background. '
    'The specific supported benefit is removing GPU-intensive acrylic rendering. Do not claim measured GPU/CPU/RAM '
    'savings, higher FPS, faster search or guaranteed speed gains. The visible result is the removed effect itself. '
    'Use these official references and verify any further claims with native web tools: '
    'https://learn.microsoft.com/en-us/windows/apps/design/style/acrylic '
    '(acrylic is GPU-intensive; disabling Transparency effects removes acrylic); '
    'https://learn.microsoft.com/en-us/windows/apps/develop/composition/composition-tailoring '
    '(the transparency setting replaces acrylic with a solid color); '
    'https://blogs.windows.com/windowsexperience/2017/04/03/windows-10-tip-five-ways-get-started-taskbar/ '
    '(Windows 10 route and effects on Start and taskbar). '
    'Keep 2-5 solution steps and all required fields. Do not return an empty steps array as an error report. '
)
WINDOW_SCHEMA = object_schema({
    'app': {'type': 'string', 'enum': ['notepad', 'calculator']},
    'placement': {'type': 'string', 'enum': ['floating', 'left', 'right']},
    'text': {'type': 'string', 'maxLength': 65},
})
SCENE_SCHEMA = object_schema({
    'surface': {'type': 'string', 'enum': list(SURFACES)},
    'title': {'type': 'string'},
    'path': {'type': 'array', 'items': {'type': 'string'}},
    'rows': {'type': 'array', 'items': object_schema({'label': {'type': 'string'}, 'value': {'type': 'string'}})},
    'focus': {'type': 'integer'}, 'action': {'type': 'string', 'enum': list(ACTIONS)},
    'before': {'type': 'string', 'maxLength': 35},
    'options': {'type': 'array', 'items': {'type': 'string'}},
    'keys': {'type': 'array', 'items': {'type': 'string'}}, 'note': {'type': 'string'},
    'windows': {'type': 'array', 'items': WINDOW_SCHEMA, 'maxItems': 2},
    'active_window': {'type': 'integer'}, 'snap_assist': {'type': 'boolean'},
    'transparency': {'type': 'string', 'enum': ['', 'on', 'off']},
})
SCHEMA = object_schema({'steps': {'type': 'array', 'items': object_schema({
    'scenes': {'type': 'array', 'items': SCENE_SCHEMA}
})}})
PROMPT = (
    'Create structured visuals for an explicitly labeled ANIMATED instructional walkthrough, not a real screen recording. '
    'Return data only, never code, HTML, commands or image URLs. Use the supplied researched tutorial plan and its official sources. '
    'Each output step corresponds to one required_shots entry in order, including the initial problem shot before solution steps. Create 1-4 short scenes per step showing its actual UI route and result. '
    'For the problem shot, visually demonstrate the symptom happening BEFORE settings or the solution, not just a title about it. '
    'Use context_menu to animate a click opening a context menu, e.g. a swapped left mouse button. Use result/shortcut for other observable pain. '
    'Do not show an enabling/disabling setting as the problem demonstration. The note describes the symptom, not the fix. '
    'Target Windows 10 only, including its exact Settings routes, left taskbar and classic context menus. Never use Windows 11 UI or Accessibility routes.  '
    'Choose the surface that actually matches the scene: settings, explorer, clipboard, notepad, desktop, start, task_manager, control_panel or windows. Do not represent unsupported applications as Settings. Use exact Windows 10 labels, not invented controls, benchmarks or results. For a Settings category selection use title Windows Settings and path Settings. For a settings page end path with its actual page title. For shortcut actions the surface is the panel opened AFTER pressing the keys. Clipboard opens a separate Clipboard panel with no emoji tabs. A context_menu scene uses surface desktop for Start or a desktop icon, explorer for a file. Its rows contain the clicked target and 2-3 genuine adjacent menu entries in their actual order; focus identifies only the clicked target. For toggle scenes include only the targeted toggle plus adjacent real settings with On/Off values; do not invent a success message. For Notepad, row labels are actual sample document text shown on separate lines. Each scene starts from the supplied visible state and clicks once halfway through; use another scene for the next navigation screen.  '
    'Each scene has title (English app/page name, <=60 chars), path (1-6 short English breadcrumb labels), '
    'rows (empty on windows, otherwise 1-4 relevant visible items, each label <=65 chars and value <=35 chars, empty value allowed), '
    'focus (zero-based targeted row or window index), action (select, toggle_on, toggle_off, shortcut, result, context_menu, choose, activate_window, snap_left, snap_right or calculate), '
    'keys (2-4 short keys for shortcut, Win and Left/Right for snap actions, one click label such as Left click for context_menu, otherwise empty), and note (one brief Egyptian Arabic instruction <=100 chars). '
    'For context_menu, rows must contain the clicked target at focus, followed by 2-3 actual menu entries for that target. A Start shortcut menu is different from a file menu. '
    'For choose, focus an actual dropdown, put the final selected option in the focused row value and its current option in before. '
    'For example, Windows 10 Devices > Mouse uses Select your primary button with before Right and final value Left. '
    'For choose, options contains all actual dropdown choices in their native order. For calculate, before is the addition expression. For all remaining actions before is empty. Outside choose, options is empty. '
    'For select, focus the menu item being opened. For toggle actions, focus the actual setting label. '
    'Preserve all conditional instructions in the note; e.g. disable Filter Keys only if enabled. '
    'For shortcut, use rows to illustrate the panel/result and keys for the shortcut. '
    'Notes are displayed on-screen, not spoken. Keep them concise. Never claim an action occurred on the user computer. '
    'For multi-window tutorials use surface windows, rows empty, and exactly two windows: Notepad and Calculator. '
    'Each window has app (notepad/calculator), placement (floating/left/right) BEFORE the action, and text '
    '(actual Notepad document text or Calculator numeric display). active_window is the zero-based foreground window BEFORE the action; '
    'focus is the window acted on. Use activate_window to click its taskbar button and bring it forward. '
    'Use snap_left or snap_right with keys [Win, Left] or [Win, Right]; these actions move/resize the focused active window, '
    'they do not open a panel. Set snap_assist true to show thumbnails after snapping and dismiss them with Esc, '
    'only when the other window is still floating. For calculate, focus the active Calculator, before contains '
    'an addition of two integers from 0 to 9999 such as 125 + 75 and its text is the verified final sum, e.g. 200. Start with Calculator cleared to 0. '
    'The renderer types the operands and clicks equals. Use result for a static hold. '
    'Preserve placements, document text and Calculator display between scenes; never reset a snapped window or reveal the answer early. '
    'For other surfaces windows is empty, active_window is 0 and snap_assist is false. '
    'For a transparency-effects tutorial, set transparency to on or off in EVERY scene, describing the state '
    'BEFORE that scene action. Show the actual Start/taskbar backgrounds, not a row saying transparent. '
    'A toggle_off of Transparency effects must use surface settings, path [Settings, Personalization, Colors], '
    'the focused row value Off and transparency on; subsequent scenes use transparency off. '
    'The opening and final scenes reopen Start using action shortcut, keys [Ctrl, Esc], identical app rows and '
    'transparency on then off respectively. Keep all intermediate scene states consistent. '
    'Outside a transparency tutorial use transparency empty. '
    'Research only if the plan is ambiguous; do not change the tip or narration.\n'
)


def validate_windows(scene):
    from pc_tips import text
    windows = scene.get('windows')
    if (not isinstance(windows, list) or len(windows) != 2
            or any(not isinstance(window, dict) for window in windows)
            or {window.get('app') for window in windows if isinstance(window.get('app'), str)} != {'notepad', 'calculator'}):
        raise ValueError('Window scenes require one Notepad and one Calculator window.')
    active = scene.get('active_window')
    if isinstance(active, bool) or not isinstance(active, int) or not 0 <= active < 2:
        raise ValueError('Choose the active window before the action.')
    occupied = set()
    result = []
    for window in windows:
        placement = window.get('placement')
        if placement not in ('floating', 'left', 'right') or placement != 'floating' and placement in occupied:
            raise ValueError('Give each window a valid, unoccupied placement.')
        occupied.add(placement)
        content = text(window.get('text'), 'Window text', 65)
        if window['app'] == 'calculator' and not re.fullmatch(r'[0-9]{1,9}', content):
            raise ValueError('Calculator needs a numeric display.')
        result.append({'app': window['app'], 'placement': placement, 'text': content})
    return result


def validate_window_action(scene, windows, before, keys):
    action, focus = scene['action'], scene['focus']
    if action not in (*WINDOW_ACTIONS, 'result'):
        raise ValueError('Use a supported window action; Win+Arrow snaps a window, not a shortcut panel.')
    if action != 'result' and action != 'activate_window' and scene['active_window'] != focus:
        raise ValueError('Activate the focused window before snapping or calculating.')
    snap = action in ('snap_left', 'snap_right')
    assist = scene.get('snap_assist', False)
    if not isinstance(assist, bool) or assist and (not snap or windows[1-focus]['placement'] != 'floating'):
        raise ValueError('Snap Assist can only follow snapping with another floating window.')
    if snap:
        side = action.removeprefix('snap_')
        if keys != ['Win', side.title()] or windows[focus]['placement'] != 'floating' or windows[1-focus]['placement'] == side:
            raise ValueError('Snap a floating active window to an empty half using Win+Left or Win+Right.')
    elif keys:
        raise ValueError('Only snap actions show window shortcut keys.')
    if action == 'calculate':
        match = re.fullmatch(r'([0-9]{1,4})\s*\+\s*([0-9]{1,4})', before)
        if (windows[focus]['app'] != 'calculator' or not match
                or windows[focus]['text'] != str(int(match[1]) + int(match[2]))):
            raise ValueError('Calculator animation requires a verified nonnegative integer addition and its sum.')
    elif before:
        raise ValueError('Only calculate uses before in a window scene.')


def validate(value, plan):
    from pc_tips import text, tutorial_shots, is_windows10_plan
    if not is_windows10_plan(plan): raise ValueError('Animated tutorials require a Windows 10 plan.')
    shots = tutorial_shots(plan)
    actual = len(value['steps']) if isinstance(value, dict) and isinstance(value.get('steps'), list) else 'no'
    if actual != len(shots):
        roles = ['problem' if i == 0 and plan.get('problem') else 'solution' for i in range(len(shots))]
        raise ValueError(f'The animated walkthrough must cover every tutorial step in order: expected {len(shots)} '
                         f'steps ({", ".join(roles)}), received {actual}. Include the problem as steps[0].')
    output = []
    previous_windows = None
    previous_transparency = None
    for step in value['steps']:
        if not isinstance(step, dict) or not isinstance(step.get('scenes'), list) or not 1 <= len(step['scenes']) <= 4:
            raise ValueError('Each animated step needs 1 to 4 scenes.')
        scenes = []
        for scene in step['scenes']:
            if not isinstance(scene, dict): raise ValueError('Invalid animated scene.')
            if scene.get('surface') not in SURFACES: raise ValueError('Choose a supported Windows 10 interface surface.')
            if any(label in json.dumps(scene, ensure_ascii=False).lower() for label in ('windows 11', 'accessibility', 'snap layouts')):
                raise ValueError('Use Windows 10 interface labels and menus only.')
            path, rows, keys = scene.get('path'), scene.get('rows'), scene.get('keys')
            if not isinstance(path, list) or not 1 <= len(path) <= 6: raise ValueError('Invalid animated menu path.')
            window_scene = scene['surface'] == 'windows'
            if not isinstance(rows, list) or (len(rows) != 0 if window_scene else not 1 <= len(rows) <= 4):
                raise ValueError('Use empty rows for windows; other surfaces need 1 to 4 interface items.')
            windows = validate_windows(scene) if window_scene else []
            if not window_scene and (scene.get('windows') or scene.get('action') in WINDOW_ACTIONS):
                raise ValueError('Window actions and window data require surface windows.')
            action, focus = scene.get('action'), scene.get('focus')
            if action not in ACTIONS or isinstance(focus, bool) or not isinstance(focus, int) or not 0 <= focus < (len(windows) if window_scene else len(rows)):
                raise ValueError('Invalid animated interaction.')
            if not isinstance(keys, list) or len(keys) > 4 or (action == 'shortcut' and len(keys) < 2) or (action == 'context_menu' and len(keys) != 1):
                raise ValueError('Invalid animated shortcut.')
            transparency = scene.get('transparency', '')
            if transparency not in ('', 'on', 'off'):
                raise ValueError('Transparency must be on, off or empty for an unrelated tutorial.')
            if previous_transparency is not None and transparency != previous_transparency:
                raise ValueError('Preserve transparency between scenes; change it with the actual Settings toggle.')
            normalized_rows = []
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('value'), str) or len(row['value']) > 35:
                    raise ValueError('Invalid animated interface value.')
                normalized_rows.append({'label': text(row.get('label'), 'Interface label', 65), 'value': row['value'].strip()})
            changes_transparency = not window_scene and action in ('toggle_on', 'toggle_off') and normalized_rows[focus]['label'] == 'Transparency effects'
            if changes_transparency:
                final = 'on' if action == 'toggle_on' else 'off'
                if (scene['surface'] != 'settings' or path != ['Settings', 'Personalization', 'Colors']
                        or transparency != ('off' if final == 'on' else 'on')
                        or normalized_rows[focus]['value'].lower() != final):
                    raise ValueError('Change Transparency effects using its Windows 10 Colors toggle and correct before/after states.')
                previous_transparency = final
            elif transparency:
                previous_transparency = transparency
            if action == 'context_menu' and len(rows) < 3:
                raise ValueError('Show the clicked target and its actual context-menu entries.')
            options = scene.get('options', [])
            if not isinstance(options, list) or len(options) > 8: raise ValueError('Invalid dropdown options.')
            options = [text(option, 'Dropdown option', 35) for option in options]
            before = scene.get('before', '')
            if not isinstance(before, str) or len(before) > 35: raise ValueError('Invalid previous dropdown value.')
            if action == 'choose' and (scene['surface'] != 'settings' or len(options) < 2 or len(set(options)) != len(options) or before.strip() not in options or normalized_rows[focus]['value'] not in options or before.strip() == normalized_rows[focus]['value']):
                raise ValueError('A Settings dropdown needs its current and chosen option.')
            if window_scene:
                validate_window_action(scene, windows, before.strip(), keys)
                if previous_windows:
                    for window in windows:
                        previous = previous_windows[window['app']]
                        if window['placement'] != previous['placement'] or (action != 'calculate' or window['app'] != 'calculator') and window['text'] != previous['text']:
                            raise ValueError('Preserve window placements and content between scenes; animate each change.')
                    if windows[scene['active_window']]['app'] != previous_active:
                        raise ValueError('Preserve the active window between scenes; use activate_window to switch.')
                    if action == 'calculate' and previous_windows['calculator']['text'] != '0':
                        raise ValueError('Begin the demonstrated addition with a cleared Calculator.')
                previous_windows = {window['app']: dict(window) for window in windows}
                previous_active = windows[scene['active_window'] if action == 'result' else focus]['app']
                if action in ('snap_left', 'snap_right'):
                    previous_windows[windows[focus]['app']]['placement'] = action.removeprefix('snap_')
            else:
                previous_windows = None
            scenes.append({'options': options, 'before': before.strip(), 'surface': scene['surface'], 'title': text(scene.get('title'), 'Animated page', 60),
                'path': [text(item, 'Menu label', 35) for item in path], 'rows': normalized_rows,
                'focus': focus, 'action': action, 'keys': [text(key, 'Shortcut key', 12) for key in keys],
                'note': text(scene.get('note'), 'Animated instruction', 100)})
            if transparency:
                scenes[-1]['transparency'] = transparency
            if window_scene:
                scenes[-1].update(windows=windows, active_window=scene['active_window'], snap_assist=scene.get('snap_assist', False))
        output.append({'scenes': scenes})
    if plan.get('topic_key') == PERFORMANCE_TOPIC:
        opening, ending = output[0]['scenes'][0], output[-1]['scenes'][-1]
        if (opening['surface'] != 'start' or ending['surface'] != 'start'
                or opening['action'] != 'shortcut' or ending['action'] != 'shortcut'
                or opening['keys'] != ['Ctrl', 'Esc'] or ending['keys'] != opening['keys']
                or opening.get('transparency') != 'on' or ending.get('transparency') != 'off'
                or opening['rows'] != ending['rows']):
            raise ValueError('Repeat the same Start opening and app list before and after removing transparency.')
    return {'steps': output}


def generate(project, data, saved):
    from pc_tips import save_state, video_info, tutorial_shots, WALKTHROUGH_STYLE
    project = Path(project).resolve()
    folder = project / 'media/pc-tips'; folder.mkdir(parents=True, exist_ok=True)
    shots = tutorial_shots(saved['plan'])
    schema = json.loads(json.dumps(SCHEMA))
    schema['properties']['steps'].update(minItems=len(shots), maxItems=len(shots),
        description='One entry per required shot, including the problem first.')
    required_shots = [{'index': i, 'role': 'problem' if i == 0 and saved['plan'].get('problem') else 'solution', **shot}
                      for i, shot in enumerate(shots)]
    request = PROMPT + f'\nReturn exactly {len(shots)} entries in steps, in required_shots order. ' + json.dumps(
        {'plan': saved['plan'], 'required_shots': required_shots}, ensure_ascii=False)
    storyboard_signature = fingerprint({'plan':saved['plan'], 'prompt':PROMPT, 'schema':schema})
    signature = fingerprint({'plan': saved['plan'], 'template': WALKTHROUGH_STYLE,
        'source': (ENGINE / 'code/src/PcWalkthrough.tsx').read_text('utf-8')})
    manifest_path = folder / 'walkthrough.json'
    previous = read_cache(manifest_path)
    if previous.get('storyboard_signature') == storyboard_signature:
        storyboard = validate(previous, saved['plan'])
    else:
        print('[PC TIPS] Designing the animated walkthrough for Windows 10.', flush=True)
        storyboard = validate(pc_tips_ai.ask(data, project, request,
                              schema, model=saved['script_model'], stage='Animated walkthrough plan',
                              validator=lambda candidate: validate(candidate, saved['plan']), repair_attempts=1,
                              quality_prompt=PROMPT + ' Check the exact Windows paths and actual before/after demonstration. ' +
                              CAPABILITIES +
                              'a text note about a symptom does not animate that symptom. Reject plans whose core effect '
                              'cannot be represented by those visuals. Tutorial: ' + json.dumps(saved['plan'], ensure_ascii=False)), saved['plan'])
    for index, (step, planned) in enumerate(zip(storyboard['steps'], tutorial_shots(saved['plan'])), 1):
        phase = 'problem' if index == 1 and saved['plan'].get('problem') else 'solution'
        step.update(os=planned['os'], phase=phase, frames=max(90 if phase == 'problem' else 240, min(150 if phase == 'problem' else 720, round(len(planned['narration'].split()) / 2.7 * 30))),
                    file=f'animated-step-{signature[:12]}-{index}.mp4')
    manifest = {**storyboard, 'signature': signature, 'storyboard_signature': storyboard_signature}
    write_json(manifest_path, manifest)
    print('[PC TIPS] Rendering clearly labeled animated tutorial scenes.', flush=True)
    process = subprocess.Popen(['node', str(ENGINE / 'code/render-pc-walkthrough.cjs'), str(manifest_path.resolve())],
        cwd=ENGINE / 'code', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    tail = []
    for line in process.stdout:
        tail = (tail + [line.strip()])[-8:]
        print(line.rstrip(), flush=True)
    if process.wait():
        raise ValueError('Animated walkthrough rendering failed. Saved scenes can be retried. ' + ' '.join(tail)[-600:])
    recordings = []
    for step in storyboard['steps']:
        target = folder / step['file']
        video_info(target)
        recordings.append({'file': target.relative_to(project).as_posix()})
    save_state(project, saved, recordings=recordings, recording_report=[], visual_source='illustrated',
               visual_note='AI-planned animated illustrations. No real desktop was recorded or changed.', walkthrough_signature=signature, walkthrough_style=WALKTHROUGH_STYLE)
    return recordings
