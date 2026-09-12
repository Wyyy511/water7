from __future__ import annotations
import pandas as pd
from .deepseek_client import chat as deepseek_chat

PATH_CN={'WS':'长期缺水压力','DR':'历史干旱','SV':'季节性供水波动'}

def _fmt(x,n=4):
    try:return f'{float(x):.{n}f}'
    except Exception:return str(x)

def baseline_brief(result:dict,material:str|None=None)->str:
    if not result or result.get('data') is None:
        return '目前还没有足够的信息形成完整的风险结果。你可以补充采购来源、地区或采购占比后继续。'
    s=result['data']['summary']; n=result['data']['nodes']
    if isinstance(s,list):s=pd.DataFrame(s)
    if isinstance(n,list):n=pd.DataFrame(n)
    if material and not s.empty and material in set(s.material):
        s=s[s.material==material];n=n[n.material==material]
    paras=[]
    for _,r in s.iterrows():
        mat=r.material;gn=n[n.material==mat]
        topc=gn.sort_values('C',ascending=False).iloc[0] if len(gn) else None
        topr=gn.sort_values('R',ascending=False).iloc[0] if len(gn) else None
        paths={'WS':float(r.path_contrib_WS or 0),'DR':float(r.path_contrib_DR or 0),'SV':float(r.path_contrib_SV or 0)}
        dom=max(paths,key=paths.get);ptotal=sum(paths.values()) or 1
        cov=float(r.get('scored_coverage',r.get('Coverage',0)) or 0);proc=float(r.get('Coverage',0) or 0)
        lines=[f'### {mat} 当前风险概览',
               f'- **综合风险指数**：{_fmt(r.PRWI)}；已识别采购覆盖 {proc*100:.1f}%，可完成风险评估的采购覆盖 {cov*100:.1f}%；在现有未知信息下，合理区间约为 [{_fmt(r.PRWI_lower)}, {_fmt(r.PRWI_upper)}]。',
               f'- **最主要的风险来源**：{PATH_CN[dom]}，约占当前风险来源的 {paths[dom]/ptotal*100:.1f}%。']
        if topc is not None:
            lines.append(f'- **对企业影响最大的供应地**：{topc.node_name}（{topc.node_id}），约占当前组合风险贡献的 {float(topc.contribution_share or 0)*100:.1f}%。')
        if topr is not None:
            extra=' 它与“对企业影响最大”的供应地不同，说明采购占比会改变企业实际优先级。' if topc is not None and topr.node_id!=topc.node_id else ''
            lines.append(f'- **自身水风险较高的供应地**：{topr.node_name}（{topr.node_id}）。'+extra)
        lines.append('- **怎么看这组结果**：风险大小和数据可信程度要分开看；如果部分采购来源未知或使用替代数据，需要优先补充核实。')
        lines.append('- **建议**：优先核实对企业影响最大的供应地及真实采购占比，并为高风险来源准备监测、库存或替代采购方案。')
        paras.append('\n'.join(lines))
    fallback='\n\n'.join(paras)
    sys=('你是企业上游供应链水风险助手。给你的数字来自已完成的计算，不能新增、重算或猜测任何数字。'
         '请用普通企业用户能理解的中文整理结果，重点说整体情况、最值得关注的供应地、为什么、数据是否完整、下一步怎么做。'
         '不要使用 Baseline、Scenario、PRWI、WS、DR、SV、BWD、DYS、CTS、OA、JSON、Schema 等后台术语。'
         '不要把综合风险指数解释成损失概率或财务损失。')
    text,_=deepseek_chat(sys,fallback,fallback)
    return text

def scenario_brief(result:dict)->str:
    if not result or result.get('data') is None:
        return '这项比较目前还缺少必要信息，暂时不能形成可靠结论。'
    d=result['data'];typ=d.get('scenario_type')
    if typ in ['PeakSeason','ExtremeDrought']:
        delta=float(d['PRWI_delta']);direction='上升' if delta>0 else ('下降' if delta<0 else '基本不变')
        title='关键用水期压力升高' if typ=='PeakSeason' else '严重干旱再次发生'
        fallback=(f'### {title}\n- 当前综合风险指数为 {_fmt(d["PRWI_baseline"])}，在这种情况下为 {_fmt(d["PRWI_scenario"])}，变化 {_fmt(delta)}，整体风险{direction}。\n'
                  '- 这是一项压力比较，用于判断脆弱点，并不表示这种情况一定会发生。\n- 建议同时关注具体供应地的变化和数据可信程度，避免只看一个总分。')
    elif typ=='AqueductFuture':
        fallback=(f'### 未来水环境发生变化\n- 在 {d.get("year")} / {d.get("path")} 的设定下，当前综合风险指数为 {_fmt(d.get("PRWI_baseline"))}，变化后为 {_fmt(d.get("PRWI_future"))}，变化 {_fmt(d.get("PRWI_delta"))}。\n'
                  '- 如果未来数据仍属于演示或压力测试数据，这一结果只用于比较趋势，不能当成确定预测。')
    elif typ=='NodeFailure':
        fallback=(f'### 主要供应节点中断\n- 受影响供应地：{d.get("target_node_name")}（{d.get("target_node_id")}），本次假设影响比例为 {float(d.get("failure_fraction_f",0))*100:.0f}%。\n'
                  f'- 预计供应损失 {_fmt(d.get("gross_loss"))}，库存可缓冲 {_fmt(d.get("inventory_used"))}，替代供应 {_fmt(d.get("replacement_allocated"))}，仍未满足的需求 {_fmt(d.get("unmet_demand"))}。\n'
                  f'- 剩余供应的综合风险为 {_fmt(d.get("conditional_PRWI"))}；采购集中度 {_fmt(d.get("procurement_hhi"))}，风险集中度 {_fmt(d.get("risk_hhi"))}。\n'
                  '- 总风险数字下降不一定代表更安全，还要同时看供应缺口、替代能力和采购是否变得更集中。')
    else:
        fallback='不同情况下的比较已经完成，可以继续查看对供应和管理决策的影响。'
    if result.get('warnings'):fallback+='\n- **需要注意**：'+'；'.join(result['warnings'])
    sys=('你是企业上游供应链水风险助手。严格使用给定结果，不创造任何新数字。'
         '请用普通用户能理解的中文说明“发生了什么变化、为什么重要、企业可以怎么做”。'
         '不要使用 Baseline、Scenario、PRWI、WS、DR、SV、BWD、DYS、CTS、OA、JSON、Schema 等后台术语；不要把压力比较写成预测。')
    text,_=deepseek_chat(sys,fallback,fallback)
    return text

def data_audit_brief(validation:dict)->str:
    if not validation:return '还没有完成资料检查。'
    out=['### 资料完整性检查'];cov=validation.get('coverage',{})
    if isinstance(cov,dict) and cov:out.append('- 已识别采购信息：'+'；'.join(f'{k} {float(v)*100:.1f}%' for k,v in cov.items()))
    for title,key in [('需要你确认','issues'),('提示','warnings'),('还缺的信息','data_gaps')]:
        vals=validation.get(key,[])
        if vals:out.append(f'- **{title}**：'+'；'.join(map(str,vals)))
    out.append('- 未识别的采购份额不会被当成 0，也不会自动把已知部分放大到 100%。')
    return '\n'.join(out)
