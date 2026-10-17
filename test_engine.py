from copy import deepcopy
from engine import *

def test_unit_equivalence():
    assert normalize_initial_data(1,'TB')==normalize_initial_data(1024,'GB')
    assert normalize_daily_ingest(1,'TB/day')==normalize_daily_ingest(1024,'GB/day')
    tb_inputs=default_base()
    gb_inputs=default_base()
    tb_inputs['initial_tb']=normalize_initial_data(1,'TB')
    gb_inputs['initial_tb']=normalize_initial_data(1024,'GB')
    tb_inputs['daily_gb']=normalize_daily_ingest(1,'TB/day')
    gb_inputs['daily_gb']=normalize_daily_ingest(1024,'GB/day')
    assert calculate_base(tb_inputs)['required_disk_tb']==calculate_base(gb_inputs)['required_disk_tb']
    try:
        normalize_initial_data(1,'GiB')
    except ValueError:
        pass
    else:
        raise AssertionError('Unsupported units should be rejected')

def test_separate_environment_results():
    prod={'base':default_base(),'ds':default_ds(),'services':[list(row) for row in DS_DEFAULTS]}
    uat=deepcopy(prod)
    uat['base']['min_workers']=25
    results={'Production':calculate_environment(prod),'UAT':calculate_environment(uat)}
    assert results['Production']['base']['workers']==19
    assert results['UAT']['base']['workers']==25
    assert results['Production']['data_services']['workers']==13
    assert results['UAT']['data_services']['workers']==13
    assert results['Production']['total_nodes']==38
    assert results['UAT']['total_nodes']==44
    base_only=calculate_environment(prod,include_ds=False)
    assert base_only['total_nodes']==22
    assert base_only['data_services'] is None

def test_sensitivity_scenarios_are_independent_and_validated():
    profile={'base':default_base(),'ds':default_ds(),'services':[list(row) for row in DS_DEFAULTS]}
    original=deepcopy(profile)
    results=calculate_sensitivity(profile,20)
    assert [row['Scenario'] for row in results]==[
        'Baseline',
        'Data +20%',
        'Peak compute +20%',
        'Data +20% & peak compute +20%',
    ]
    assert results[0]['Base workers']==19
    assert results[1]['Required raw disk (TB)']>results[0]['Required raw disk (TB)']
    assert results[1]['Base workers']>=results[0]['Base workers']
    assert results[2]['Base workers']>=results[0]['Base workers']
    assert results[3]['Base workers']>=results[1]['Base workers']
    assert all(row['Data Services workers (held constant)']==13 for row in results)
    assert profile==original
    for value in (-1,101,float('nan')):
        try:
            calculate_sensitivity(profile,value)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid sensitivity percentages should be rejected')

def test_base():
    defaults=default_base()
    assert defaults['compression']==3
    assert defaults['cold_share']==.4
    assert defaults['growth']==.2
    assert defaults['years']==3
    x=calculate_base(default_base())
    assert x['workers']==19
    assert x['masters']==3
    assert x['candidates']['Memory']==19
    assert x['design_raw_tb']==848.73046875
    assert x['stored_tb']==282.91015625
    assert x['candidates']['Storage']==13
    assert x['forecast'][0]=={'Year':1,'Ingest added (TB)':178.22,'Cumulative raw (TB)':378.22}
    expected=((200+500*365/1024+500*365*1.2/1024+500*365*1.2**2/1024)/3)*2.4*1.3/.85
    assert abs(x['required_disk_tb']-expected)<1e-10
    assert abs(x['required_disk_tb']-1038.4466911764707)<1e-10

def test_base_rejects_invalid_values():
    for key,value in [('initial_tb',-1),('daily_gb',float('nan')),('years',1.5),('daily_gb',1e308)]:
        inputs=default_base()
        inputs[key]=value
        try:
            calculate_base(inputs)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Invalid {key} should be rejected')
    inputs=default_base()
    inputs['initial_tb']=0
    inputs['daily_gb']=0
    try:
        calculate_base(inputs)
    except ValueError:
        pass
    else:
        raise AssertionError('Zero initial data and ingest should be rejected')

def test_base_sizing_drivers():
    inputs=default_base()
    inputs['initial_tb']=10000
    assert calculate_base(inputs)['driver']=='Storage'
    inputs=default_base()
    inputs['peak_vcores']=5000
    assert calculate_base(inputs)['driver']=='CPU'
    inputs=default_base()
    inputs['min_workers']=25
    result=calculate_base(inputs)
    assert result['workers']==25 and result['driver']=='Policy minimum'
    inputs=default_base()
    inputs.update(initial_tb=1,daily_gb=0,peak_vcores=0,peak_ram=0)
    result=calculate_base(inputs)
    assert result['workers']==9 and result['driver']=='EC minimum'

def test_ds_rejects_invalid_values():
    inputs=default_ds()
    inputs['headroom']=-0.1
    try:
        calculate_ds(inputs,DS_DEFAULTS)
    except ValueError:
        pass
    else:
        raise AssertionError('Negative DS headroom should be rejected')
    services=[list(row) for row in DS_DEFAULTS]
    services[0][2]=-1
    try:
        calculate_ds(default_ds(),services)
    except ValueError:
        pass
    else:
        raise AssertionError('Negative DS per-unit resources should be rejected')

def test_ds():
    x=calculate_ds(default_ds(),DS_DEFAULTS)
    assert x['workers']==13
    assert x['masters']==3
    assert x['total_nodes']==16

if __name__=='__main__':
    test_unit_equivalence();test_separate_environment_results();test_sensitivity_scenarios_are_independent_and_validated();test_base();test_base_rejects_invalid_values();test_base_sizing_drivers();test_ds_rejects_invalid_values();test_ds();print('All test checks passed')
