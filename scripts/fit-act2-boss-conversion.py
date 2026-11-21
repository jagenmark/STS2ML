"""Select boss plans and the last campfire threshold on paired natural continuations."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.run_bundle import freeze_bundle, load_bundle


def read_group(folder, partition, reserved):
    meta = json.loads((folder/"design.json").read_bytes())
    seeds = set(meta["seeds"])
    if meta["partition"] != partition or len(seeds) != len(meta["seeds"]) or seeds & reserved:
        raise ValueError("Invalid seed partition in "+str(folder))
    rows, excluded = [], []
    for seed in sorted(seeds):
        path = folder/(seed+".json.gz")
        path = path if path.is_file() else folder/(seed+".json")
        if not path.is_file():
            err = folder/(seed+".error.json")
            if not err.is_file():
                raise ValueError("Missing result for "+seed)
            excluded.append(seed)
            continue
        with (gzip.open(path,"rt") if path.suffix==".gz" else path.open()) as stream:
            row = json.load(stream)
        if row["seed"] != seed:
            raise ValueError("Misidentified training root")
        if row.get("errors") or row.get("ineligible"):
            excluded.append(seed)
        else:
            rows.append(row)
    return meta, rows, excluded


def score(outcomes):
    rows=list(outcomes)
    return (sum(r["won"] for r in rows), sum(r["hp"] for r in rows), -sum(r["remaining"] for r in rows))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("training","development","camp-training","camp-development","seed-lock","bundle","output"):
        p.add_argument("--"+key, type=Path, required=True)
    p.add_argument("--draft",type=Path,help="Independently accepted preparation bundle")
    a=p.parse_args()
    splits=json.loads(a.seed_lock.read_bytes())["seeds"]
    protected=set(splits["test"])
    train=read_group(a.training,"training",protected|set(splits["development"]))
    dev=read_group(a.development,"development",protected|set(splits["train"]))
    camp=read_group(a.camp_training,"training",protected|set(splits["development"]))
    camp_dev=read_group(a.camp_development,"development",protected|set(splits["train"]))
    bundle_hash=hashlib.sha256(a.bundle.read_bytes()).hexdigest()
    for first,second in ((train,dev),(camp,camp_dev)):
        if first[0]["label_provenance"] != second[0]["label_provenance"] or first[0]["label_provenance"]["bundle_sha256"] != bundle_hash:
            raise ValueError("Paired labels were collected with different teachers or weights")
        if set(first[0]["seeds"]) & set(second[0]["seeds"]):
            raise ValueError("Development and training share a seed")
    if train[0]["variants"] != dev[0]["variants"]:
        raise ValueError("Development and training evaluated different boss plans")
    variants=train[0]["variants"]
    chosen={}
    detail={}
    by_boss=defaultdict(list)
    for row in train[1]:
        by_boss[row["boss"]].append(row)
    for boss,rows in by_boss.items():
        validation=[r for r in dev[1] if r["boss"]==boss]
        options=rows[0]["outcomes"]
        tr={n:score(r["outcomes"][n] for r in rows) for n in options}
        va={n:score(r["outcomes"][n] for r in validation) for n in options}
        best=max(options,key=lambda n:(tr[n],n=="control"))
        accepted=(bool(validation) and tr[best][:2]>tr["control"][:2] and va[best][0]>=va["control"][0]
                  and (tr[best][0]>tr["control"][0] or va[best][0]>va["control"][0]))
        if accepted:
            chosen[boss]=variants[best]["act2_boss_plans"][boss]
        detail[boss]={"train_n":len(rows),"development_n":len(validation),"train":tr,"development":va,
                      "training_winner":best,"accepted":accepted}
    camp_results={}
    for name,group in (("train",camp),("development",camp_dev)):
        rows=[r for r in group[1] if set(r["branches"])=={"HEAL","SMITH"} and r["default"] in r["branches"]]
        def option(r,t):
            return r["default"] if t=="control" else ("HEAL" if r["hp"]/r["max_hp"] < t else "SMITH")
        camp_results[name]={"n":len(rows),"scores":{
            t:score(r["branches"][option(r,t)] for r in rows) for t in ("control",0.55,0.65,0.77,0.85,0.95,1.0)}}
    cs=camp_results["train"]["scores"]
    threshold=max((k for k in cs if k!="control"),key=lambda k:(cs[k],-abs(k-.77)))
    accepted=cs[threshold][0]>cs["control"][0] and camp_results["development"]["scores"][threshold][0]>=camp_results["development"]["scores"]["control"][0]
    role,settings=load_bundle(a.bundle)
    a.output.mkdir(parents=True,exist_ok=False)
    if a.draft:
        draft_role,draft=load_bundle(a.draft)
        if draft_role!=role or any(hashlib.sha256(v.read_bytes()).digest()!=hashlib.sha256(draft[k].read_bytes()).digest()
                                  for k,v in settings.items() if isinstance(v,Path) and k!="strategy_model"):
            raise ValueError("Preparation trial must change only the strategy model")
        settings["strategy_model"]=draft["strategy_model"]
    if chosen:
        data=json.loads(settings["encounter_model"].read_bytes())
        data["act2_boss_plans"]=chosen
        settings["encounter_model"]=a.output/"selected-encounter.json"
        save_json(settings["encounter_model"],data)
    if accepted:
        data=json.loads(settings["deck_model"].read_bytes())
        data["act2_final_rest_threshold"]=threshold
        settings["deck_model"]=a.output/"selected-deck.json"
        save_json(settings["deck_model"],data)
    dest=freeze_bundle({"args":{**settings,"roles":[role]}},a.output/"challenger")
    save_json(a.output/"fit.json", {"bosses":detail,"plans":chosen,"campfires":camp_results,
              "campfire_threshold":threshold if accepted else None,"campfire_candidate":threshold,
              "excluded":{name:g[2] for name,g in (("train",train),("development",dev),("camp",camp),("camp-dev",camp_dev))},
              "training_provenance":train[0]["label_provenance"],"campfire_provenance":camp[0]["label_provenance"],
              "draft":a.draft.parent.name if a.draft else None,"policy_sha256":hashlib.sha256(dest.read_bytes()).hexdigest(),
              "seed_lock_sha256":hashlib.sha256(a.seed_lock.read_bytes()).hexdigest()})


if __name__=="__main__":
    main()
