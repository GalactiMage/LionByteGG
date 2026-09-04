import arena_db, os
arena_db.init_arena_db(os.path.join(os.path.dirname(os.getcwd()), 'data', 'arena_signins.json'))
recs = arena_db.get_all()
bad = {'zznormalqa@pnw.edu', 'zzbantest@pnw.edu'}
keep = [r for r in recs if (r.get('email') or '').lower() not in bad and (r.get('name') or '') not in ('QA Normal','QA Ban')]
removed = len(recs) - len(keep)
arena_db.replace_all(keep)
# clear flags feed (qa noise + this morning's test spam)
fp = os.path.join(os.path.dirname(os.getcwd()), 'data', 'arena_signin_flags.json')
open(fp, 'w', encoding='utf-8').write('[]')
print(f"removed {removed} QA record(s); kept {len(keep)}; flags cleared")
