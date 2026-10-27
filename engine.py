"""Transparent, deterministic reproduction of the Base/DS quick calculators.
These are reference planning estimates, NOT a vendor-certified bill of materials.
"""
from copy import deepcopy
from math import ceil, isclose, isfinite

RULES_VERSION = 'Workbook 1.0 (October 2026)'
RULES_SOURCE = 'reference/Cloudera_CDP_Capacity_Planning_Annotated.xlsx'
GB_PER_TB = 1024


def normalize_initial_data(value, unit):
    _finite_number(value, 'Initial data')
    if value < 0:
        raise ValueError('Initial data must not be negative')
    if unit == 'TB':
        return value
    if unit == 'GB':
        return value / GB_PER_TB
    raise ValueError(f'Unsupported initial-data unit: {unit}')


def normalize_daily_ingest(value, unit):
    _finite_number(value, 'Daily ingest')
    if value < 0:
        raise ValueError('Daily ingest must not be negative')
    if unit == 'GB/day':
        return value
    if unit == 'TB/day':
        return value * GB_PER_TB
    raise ValueError(f'Unsupported daily-ingest unit: {unit}')


def _finite_number(value, name):
    try:
        valid = isinstance(value, (int, float)) and isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{name} must be a finite number')
    return value

def calculate_base(c, data_classes=None):
    for k, value in c.items():
        _finite_number(value, k)
    for k in ('compression','replication','ec_overhead','disk_tb','disks_per_worker','worker_vcores','worker_ram'):
        if c[k] <= 0: raise ValueError(f'{k} must be greater than zero')
    for k in ('initial_tb','daily_gb','peak_vcores','peak_ram','scratch'):
        if c[k] < 0: raise ValueError(f'{k} must not be negative')
    if not 0 <= c['growth'] <= 3: raise ValueError('Growth must be between 0 and 300%')
    if not 0 < c['utilization'] <= 1: raise ValueError('Utilization must be between 0 and 100%')
    if not 0 <= c['cold_share'] <= 1: raise ValueError('Cold share must be between 0 and 100%')
    if not 0 <= c['reservation'] < 1: raise ValueError('Reservation must be below 100%')
    if not isinstance(c['years'], int) or not 1 <= c['years'] <= 5: raise ValueError('Design year must be an integer from 1 to 5')
    if not isinstance(c['disks_per_worker'], int) or c['disks_per_worker'] < 1: raise ValueError('Disks per worker must be a positive integer')
    if not isinstance(c['min_workers'], int) or c['min_workers'] < 0: raise ValueError('Minimum workers must be a non-negative integer')
    if not data_classes and c['initial_tb'] == 0 and c['daily_gb'] == 0: raise ValueError('Initial data and daily ingest cannot both be zero')
    class_details=[]
    if data_classes:
        forecast=[{'Year':year,'Ingest added (TB)':0.,'Cumulative raw (TB)':0.} for year in range(1,6)]
        yearly_required=[0.]*5
        design_raw=stored=required=0.
        protected=0.
        derived_vcores=derived_ram=0.
        ratio_vcores=0.
        for index,row in enumerate(data_classes,1):
            name=str(row.get('Data class','')).strip()
            if not name:
                raise ValueError(f'Data class row {index} needs a name')
            values={}
            for key in ('Initial raw data (TB)','Daily ingest (GB/day)','Annual growth (%)','Compression ratio (x)','Cold data (%)','Retention years','Audit/log growth (TB/year)','Average file size (MB)','vCores per TB','RAM GB per TB','Concurrent queries','vCores per query','RAM GB per query','vCores per GB RAM'):
                values[key]=row.get(key,0)
                _finite_number(values[key],f'{name}: {key}')
                if values[key]<0:
                    raise ValueError(f'{name}: {key} must not be negative')
            if values['Compression ratio (x)']<=0 or values['Average file size (MB)']<=0:
                raise ValueError(f'{name}: compression and average file size must be greater than zero')
            if values['Annual growth (%)']>300 or values['Cold data (%)']>100:
                raise ValueError(f'{name}: annual growth must be at most 300% and cold data at most 100%')
            if not float(values['Retention years']).is_integer() or not 1<=values['Retention years']<=5:
                raise ValueError(f'{name}: retention years must be a whole number from 1 to 5')
            if not float(values['Concurrent queries']).is_integer():
                raise ValueError(f'{name}: concurrent queries must be a whole number')
            growth=values['Annual growth (%)']/100
            cold_share=values['Cold data (%)']/100
            annual=[];raw=values['Initial raw data (TB)']
            for year in range(1,6):
                ingest=values['Daily ingest (GB/day)']*365*(1+growth)**(year-1)/GB_PER_TB
                audit=values['Audit/log growth (TB/year)']
                _finite_number(ingest,f'{name}: year {year} ingest')
                _finite_number(raw+ingest+audit,f'{name}: year {year} forecast')
                raw+=ingest+audit
                annual.append((ingest,audit,raw))
                forecast[year-1]['Ingest added (TB)']+=ingest+audit
                forecast[year-1]['Cumulative raw (TB)']+=raw
            horizon=c['years']
            retained_start=max(0,horizon-int(values['Retention years']))
            retained_raw=values['Initial raw data (TB)']+sum(ingest+audit for ingest,audit,_ in annual[retained_start:horizon])
            class_stored=retained_raw/values['Compression ratio (x)']
            class_protection=cold_share*c['ec_overhead']+(1-cold_share)*c['replication']
            class_required=class_stored*class_protection*(1+c['scratch'])/c['utilization']
            _finite_number(class_required,f'{name}: required raw disk')
            design_raw+=retained_raw
            stored+=class_stored
            protected+=class_stored*class_protection
            required+=class_required
            derived_vcores+=retained_raw*values['vCores per TB']+int(values['Concurrent queries'])*values['vCores per query']
            class_ram=retained_raw*values['RAM GB per TB']+int(values['Concurrent queries'])*values['RAM GB per query']
            derived_ram+=class_ram
            ratio_vcores+=class_ram*values['vCores per GB RAM']
            for year_index in range(5):
                retained_for_year=values['Initial raw data (TB)']+sum(ingest+audit for ingest,audit,_ in annual[max(0,year_index+1-int(values['Retention years'])):year_index+1])
                yearly_required[year_index]+=retained_for_year/values['Compression ratio (x)']*class_protection*(1+c['scratch'])/c['utilization']
                _finite_number(yearly_required[year_index],f'{name}: year {year_index+1} required raw disk')
            object_count=retained_raw*1024*1024/values['Average file size (MB)']
            _finite_number(object_count,f'{name}: estimated files/objects')
            class_details.append({
                'Data class':name,
                'Design raw data after retention (TB)':retained_raw,
                'Stored after compression (TB)':class_stored,
                'Protection factor':class_protection,
                'Required raw disk (TB)':class_required,
                'Estimated files/objects':object_count,
                'Workload profile':row.get('Workload profile','Medium'),
                'Retention years':int(values['Retention years']),
            })
        if design_raw==0:
            raise ValueError('Data classes must include non-zero initial data, ingest, or audit/log growth')
        for year in forecast:
            year['Ingest added (TB)']=round(year['Ingest added (TB)'],2)
            year['Cumulative raw (TB)']=round(year['Cumulative raw (TB)'],2)
        protection=protected/stored if stored else 0
        derived_vcores=max(derived_vcores,ratio_vcores)
        peak_vcores=max(c['peak_vcores'],derived_vcores)
        peak_ram=max(c['peak_ram'],derived_ram)
    else:
        forecast=[]; raw=c['initial_tb'];yearly_required=[]
        for y in range(1,6):
            added=c['daily_gb']*365*(1+c['growth'])**(y-1)/1024
            _finite_number(added, f'Year {y} ingest forecast')
            raw+=added
            _finite_number(raw, f'Year {y} cumulative forecast')
            yearly_required.append((raw/c['compression'])*(c['cold_share']*c['ec_overhead']+(1-c['cold_share'])*c['replication'])*(1+c['scratch'])/c['utilization'])
            forecast.append({'Year':y,'Ingest added (TB)':round(added,2),'Cumulative raw (TB)':round(raw,2),'_raw_tb':raw})
        design_raw=forecast[c['years']-1]['_raw_tb']
        forecast=[{key:value for key,value in year.items() if key != '_raw_tb'} for year in forecast]
        stored=design_raw/c['compression']
        protection=c['cold_share']*c['ec_overhead']+(1-c['cold_share'])*c['replication']
        required=stored*protection*(1+c['scratch'])/c['utilization']
        protected=stored*protection
        peak_vcores=c['peak_vcores']
        peak_ram=c['peak_ram']
    node_disk=c['disk_tb']*c['disks_per_worker']
    for name, value in (('Stored data',stored),('Protection factor',protection),('Required raw disk',required),('Worker disk capacity',node_disk)):
        _finite_number(value, name)
    storage=ceil(required/node_disk)
    cpu_ratio=peak_vcores/(c['worker_vcores']*(1-c['reservation']))
    memory_ratio=peak_ram/(c['worker_ram']*(1-c['reservation']))
    _finite_number(cpu_ratio,'CPU worker requirement')
    _finite_number(memory_ratio,'Memory worker requirement')
    cpu=ceil(cpu_ratio)
    memory=ceil(memory_ratio)
    ec_min=0
    if c['cold_share']>0:
        for overhead,minimum_nodes in ((5/3,5),(1.5,9),(1.4,14)):
            if isclose(c['ec_overhead'],overhead,rel_tol=0,abs_tol=1e-9):
                ec_min=minimum_nodes
                break
    candidates={'Storage':storage,'CPU':cpu,'Memory':memory,'EC minimum':ec_min,'Policy minimum':c['min_workers']}
    workers=max(candidates.values()); driver=next(k for k,v in candidates.items() if v==workers)
    yearly_capacity=[]
    for year_index,required_for_year in enumerate(yearly_required):
        yearly_storage=ceil(required_for_year/node_disk)
        yearly_candidates={'Storage':yearly_storage,'CPU':cpu,'Memory':memory,'EC minimum':ec_min,'Policy minimum':c['min_workers']}
        yearly_workers=max(yearly_candidates.values())
        yearly_driver=next(key for key,value in yearly_candidates.items() if value==yearly_workers)
        yearly_capacity.append({'Year':year_index+1,'Required raw disk (TB)':required_for_year,'Base workers':yearly_workers,'Sizing driver':yearly_driver})
    warnings=[]
    if node_disk>100:warnings.append('Data disks exceed workbook guidance of 100 TB per worker. Change hardware profile.')
    if peak_vcores==0 or peak_ram==0:warnings.append('Compute demand was not supplied: worker counts may substantially underestimate demand.')
    if ec_min:warnings.append(f'Erasure coding requires at least {ec_min} nodes for this scheme; placement and failure-domain review is still required.')
    if not c['ha']:warnings.append('HA disabled: master nodes and service availability must be manually designed; workbook assumes production HA.')
    if not data_classes and c['initial_tb']==0 and c['daily_gb']==0:warnings.append('No data volume supplied.')
    return {'forecast':forecast,'yearly_capacity':yearly_capacity,'data_classes':class_details,'design_raw_tb':design_raw,'stored_tb':stored,'protection':protection,'protected_tb':protected,'required_disk_tb':required,'node_disk_tb':node_disk,'candidates':candidates,'workers':workers,'driver':driver,'masters':5 if workers>200 else (3 if c['ha'] else 1),'total_nodes':workers+(5 if workers>200 else (3 if c['ha'] else 1)),'installed_tb':workers*node_disk,'worker_ccu':c['worker_vcores']/6+c['worker_ram']/12,'total_worker_ccu':workers*(c['worker_vcores']/6+c['worker_ram']/12),'peak_vcores_used':peak_vcores,'peak_ram_used':peak_ram,'warnings':warnings}

DS_DEFAULTS=[
 ('CDW Database Catalog',1,4,16,100,0,'Assumption'),
 ('CDW virtual warehouses',2,2,8,100,0,'Block: reference; CPU/RAM assumptions'),
 ('CDW Impala coordinators',4,12,128,0,600,'2 per warehouse for HA'),
 ('CDW Impala executors',20,12,128,0,600,'RAM/cache reference; CPU assumption'),
 ('CDW Hive LLAP executors',0,12,128,0,600,'RAM/cache reference; CPU assumption'),
 ('Data Visualization instances',1,4,16,50,0,'Assumption'),
 ('CDE services',1,16,64,200,0,'Reference'),
 ('CDE concurrent jobs',10,8,32,0,0,'Average/job assumption'),
 ('Cloudera AI workspaces',1,32,128,2600,0,'Reference minimum'),
 ('Cloudera AI concurrent sessions',20,2,8,0,0,'Session profile assumption')]

def calculate_ds(c,services):
    for k, value in c.items():
        _finite_number(value, k)
    if any(c[k]<=0 for k in ('vcores','ram','block','cache')):raise ValueError('DS hardware capacities must be positive')
    if c['block']<=c['block_reserve']:raise ValueError('Block storage per worker must exceed Control Plane reserve')
    if c['block_reserve']<0:raise ValueError('Control Plane reserve must not be negative')
    if not 0<=c['os_overhead']<1:raise ValueError('OS overhead must be below 100%')
    if c['headroom']<0:raise ValueError('Scaling headroom must not be negative')
    if not isinstance(c['min_workers'], int) or c['min_workers']<0:raise ValueError('Minimum DS workers must be a non-negative integer')
    connected_environments=c.get('connected_environments',1)
    _finite_number(connected_environments,'Data Services connected environment count')
    if not float(connected_environments).is_integer() or connected_environments<1:
        raise ValueError('Connected environment count must be a positive whole number')
    externalfs_tb=c.get('externalfs_tb',0)
    _finite_number(externalfs_tb,'ExternalFS storage')
    if externalfs_tb<0:
        raise ValueError('ExternalFS storage must not be negative')
    control_plane_per_environment={key:c.get(key,0) for key in ('control_plane_vcores_per_environment','control_plane_ram_gb_per_environment','control_plane_block_gb_per_environment')}
    for key,value in control_plane_per_environment.items():
        _finite_number(value,f'Data Services {key}')
        if value<0:
            raise ValueError(f'Data Services {key} must not be negative')
    gpu_nodes=c.get('gpu_nodes',0)
    gpus_per_node=c.get('gpus_per_node',0)
    for key,value in (('GPU node count',gpu_nodes),('GPUs per node',gpus_per_node)):
        _finite_number(value,f'Data Services {key}')
        if value<0 or not float(value).is_integer():
            raise ValueError(f'Data Services {key} must be a non-negative whole number')
    if gpu_nodes and not gpus_per_node:
        raise ValueError('Set GPUs per node when GPU nodes are included')
    demand={'vcores':0,'ram':0,'block':0,'cache':0};detail=[]
    for s in services:
        name,qty,cores,ram,block,cache,basis=s
        for label,value in [('quantity',qty),('vCores per unit',cores),('RAM per unit',ram),('block per unit',block),('cache per unit',cache)]:
            _finite_number(value,f'{name}: {label}')
            if value<0:raise ValueError(f'{name}: {label} must not be negative')
        item={'Component':name,'Quantity':qty,'vCores':qty*cores,'RAM (GB)':qty*ram,'Block (GB)':qty*block,'Cache (GB)':qty*cache,'Basis':basis}
        detail.append(item)
        for key,val in [('vcores',cores),('ram',ram),('block',block),('cache',cache)]:
            demand[key]+=qty*val
            _finite_number(demand[key],f'Data Services {key} demand')
    control_plane_demand={
        'vcores':connected_environments*control_plane_per_environment['control_plane_vcores_per_environment'],
        'ram':connected_environments*control_plane_per_environment['control_plane_ram_gb_per_environment'],
        'block':connected_environments*control_plane_per_environment['control_plane_block_gb_per_environment'],
    }
    demand['vcores']+=control_plane_demand['vcores']
    demand['ram']+=control_plane_demand['ram']
    demand['block']+=control_plane_demand['block']
    for key,value in demand.items():
        _finite_number(value,f'Data Services {key} demand')
    ratios={'CPU':demand['vcores']*(1+c['headroom'])/(c['vcores']*(1-c['os_overhead'])),'Memory':demand['ram']*(1+c['headroom'])/(c['ram']*(1-c['os_overhead'])),'Block storage':demand['block']*(1+c['headroom'])/(c['block']-c['block_reserve']),'CDW cache':demand['cache']/c['cache']}
    for name,value in ratios.items():_finite_number(value,f'Data Services {name} worker requirement')
    candidates={name:ceil(value) for name,value in ratios.items()}
    workers=max(*candidates.values(),c['min_workers']);driver=next((k for k,v in candidates.items() if v==workers),'Minimum workers')
    warnings=[]
    if gpu_nodes:warnings.append('GPU nodes are added as a manual Data Services inventory count; GPU-specific workload demand and utilization are not calculated.')
    if sum(s[1] for s in services)==0:warnings.append('No Data Services workloads selected. Do not deploy an empty DS cluster based solely on this result.')
    if sum(s[1] for s in services if 'CDW' in s[0])>0 and workers<10:warnings.append('The workbook describes 10 DS workers as a recommended CDW baseline; assess desired availability and performance.')
    cde_jobs=sum(item['Quantity'] for item in detail if item['Component']=='CDE concurrent jobs')
    return {'details':detail,'demand':demand,'control_plane_demand':control_plane_demand,'connected_environments':int(connected_environments),'externalfs_tb':externalfs_tb,'cde_jobs_per_worker':cde_jobs/workers if workers else 0,'candidates':candidates,'workers':workers,'gpu_nodes':int(gpu_nodes),'gpus_per_node':int(gpus_per_node),'driver':driver,'masters':3 if c['ha'] else 1,'total_nodes':workers+(3 if c['ha'] else 1)+int(gpu_nodes),'warnings':warnings}

def default_base():
    return dict(initial_tb=200.,daily_gb=500.,growth=.20,years=3,compression=3.,cold_share=.40,replication=3.,ec_overhead=1.5,scratch=.30,utilization=.85,disk_tb=8.,disks_per_worker=10,worker_vcores=96,worker_ram=384.,reservation=.15,peak_vcores=800.,peak_ram=6000.,min_workers=3,ha=True)

def default_ds():return dict(vcores=80,ram=415.,block=4000.,cache=1800.,block_reserve=1024.,os_overhead=.10,headroom=.20,min_workers=4,ha=True,gpu_nodes=0,gpus_per_node=0,connected_environments=1,control_plane_vcores_per_environment=0.,control_plane_ram_gb_per_environment=0.,control_plane_block_gb_per_environment=0.,externalfs_tb=0.)

def default_kafka():
    return dict(enabled=False,throughput_mb_s=0.,partitions=0,retention_days=3,replication=3,
                node_throughput_mb_s=0.,partitions_per_node=0)

def default_licensing():
    return dict(enabled=False,included_ccu=0.,included_tb=0.,excluded_tb=0.)

def default_kudu():
    return dict(enabled=False,data_tb=0.,replication=3.,disk_per_node_tb=0.)

SERVICE_POOL_DEFAULTS=[
    ('Apache NiFi',False,0,0.,0.,0.),
    ('Apache HBase',False,0,0.,0.,0.),
    ('Management / Control Plane',False,0,0.,0.,0.),
    ('Ranger / Atlas',False,0,0.,0.,0.),
    ('External database',False,0,0.,0.,0.),
    ('Other dedicated service',False,0,0.,0.,0.),
]

def calculate_kudu(c):
    if not isinstance(c.get('enabled',False),bool):
        raise ValueError('Kudu enabled setting must be a boolean')
    if not c.get('enabled',False):
        return None
    for key in ('data_tb','replication','disk_per_node_tb'):
        _finite_number(c[key],f'Kudu {key}')
        if c[key]<0:
            raise ValueError(f'Kudu {key} must not be negative')
    if c['data_tb']<=0 or c['replication']<=0 or c['disk_per_node_tb']<=0:
        raise ValueError('Kudu raw data, replication and disk per node must be greater than zero')
    protected_tb=c['data_tb']*c['replication']
    _finite_number(protected_tb,'Kudu protected data')
    return {'protected_tb':protected_tb,'workers':ceil(protected_tb/c['disk_per_node_tb'])}

def calculate_service_pools(rows):
    details=[];total_nodes=0
    for index,row in enumerate(rows,1):
        name,required,nodes,vcores,ram,disk=row
        if not isinstance(name,str) or not name.strip():
            raise ValueError(f'Dedicated service row {index} needs a name')
        if not isinstance(required,bool):
            raise ValueError(f'{name}: required flag must be boolean')
        for label,value in (('nodes',nodes),('vCores per node',vcores),('RAM per node',ram),('disk per node',disk)):
            _finite_number(value,f'{name}: {label}')
            if value<0:
                raise ValueError(f'{name}: {label} must not be negative')
        if not float(nodes).is_integer():
            raise ValueError(f'{name}: node count must be a whole number')
        if required and nodes<1:
            raise ValueError(f'{name}: enter at least one planned node for a required service')
        if required or nodes:
            total_nodes+=int(nodes)
            details.append({'Service':name,'Required':required,'Nodes':int(nodes),'vCores / node':vcores,'RAM GB / node':ram,'Disk TB / node':disk})
    return {'details':details,'total_nodes':total_nodes}

def calculate_kafka(c):
    if not isinstance(c.get('enabled',False),bool):
        raise ValueError('Kafka enabled setting must be a boolean')
    if not c.get('enabled',False):
        return None
    for key in ('throughput_mb_s','partitions','retention_days','replication','node_throughput_mb_s','partitions_per_node'):
        _finite_number(c[key],f'Kafka {key}')
    if c['throughput_mb_s']<0 or c['partitions']<0:
        raise ValueError('Kafka throughput and partition count must not be negative')
    if c['retention_days']<=0 or c['replication']<=0:
        raise ValueError('Kafka retention and replication must be greater than zero')
    if c['node_throughput_mb_s']<=0 or c['partitions_per_node']<=0:
        raise ValueError('Set positive per-node Kafka throughput and partition capacities to calculate nodes')
    if not isinstance(c['partitions'],int) or not isinstance(c['partitions_per_node'],int):
        raise ValueError('Kafka partition counts must be whole numbers')
    storage_tb=c['throughput_mb_s']*86400*c['retention_days']*c['replication']/(1024*1024)
    throughput_nodes=ceil(c['throughput_mb_s']/c['node_throughput_mb_s'])
    partition_nodes=ceil(c['partitions']/c['partitions_per_node'])
    _finite_number(storage_tb,'Kafka retained storage')
    return {
        'throughput_nodes':throughput_nodes,
        'partition_nodes':partition_nodes,
        'workers':max(throughput_nodes,partition_nodes),
        'storage_tb':storage_tb,
        'warnings':['Kafka is estimated as a separate dedicated pool; include its storage in the Base data forecast only if Kafka data is hosted there.'],
    }

def calculate_licensing(base, c):
    if not isinstance(c.get('enabled',False),bool):
        raise ValueError('Licensing enabled setting must be a boolean')
    if not c.get('enabled',False):
        return None
    for key in ('included_ccu','included_tb','excluded_tb'):
        _finite_number(c[key],f'Licensing {key}')
        if c[key]<0:
            raise ValueError(f'Licensing {key} must not be negative')
    used_tb=max(0,base['design_raw_tb']-c['excluded_tb'])
    return {
        'estimated_ccu':base['total_worker_ccu'],
        'included_ccu':c['included_ccu'],
        'excess_ccu':max(0,base['total_worker_ccu']-c['included_ccu']),
        'estimated_included_tb':used_tb,
        'included_tb':c['included_tb'],
        'excess_tb':max(0,used_tb-c['included_tb']),
        'excluded_tb':min(base['design_raw_tb'],c['excluded_tb']),
        'warning':'Indicative only. Confirm product, edition, subscription metric, exclusions, and effective licensing rules with Cloudera.',
    }


def calculate_environment(profile, include_ds=True):
    capacity_percent=profile.get('capacity_percent',100)
    _finite_number(capacity_percent,'Environment capacity percentage')
    if not 1<=capacity_percent<=500:
        raise ValueError('Environment capacity percentage must be between 1 and 500%')
    scale=capacity_percent/100
    scaled_profile=deepcopy(profile)
    base_inputs=scaled_profile['base']
    for key in ('initial_tb','daily_gb','peak_vcores','peak_ram'):
        base_inputs[key]*=scale
    for row in scaled_profile.get('data_classes',[]):
        for key in ('Initial raw data (TB)','Daily ingest (GB/day)','Audit/log growth (TB/year)'):
            row[key]=row.get(key,0)*scale
        row['Concurrent queries']=ceil(row.get('Concurrent queries',0)*scale)
    if include_ds:
        for row in scaled_profile['services']:
            row[1]=ceil(row[1]*scale)
        scaled_profile['ds']['gpu_nodes']=ceil(scaled_profile['ds'].get('gpu_nodes',0)*scale)
    kafka_inputs=default_kafka()
    kafka_inputs.update(scaled_profile.get('kafka',{}))
    kafka_inputs['throughput_mb_s']*=scale
    kafka_inputs['partitions']=ceil(kafka_inputs['partitions']*scale)
    kudu_inputs=default_kudu()
    kudu_inputs.update(scaled_profile.get('kudu',{}))
    kudu_inputs['data_tb']*=scale
    service_rows=[list(row) for row in scaled_profile.get('service_pools',[])]
    scaled_profile['service_pools']=service_rows
    for row in service_rows:
        row[2]=ceil(row[2]*scale)
    base=calculate_base(base_inputs,scaled_profile.get('data_classes'))
    ds=calculate_ds(scaled_profile['ds'],scaled_profile['services']) if include_ds else None
    kafka=calculate_kafka(kafka_inputs)
    kudu=calculate_kudu(kudu_inputs)
    dedicated=calculate_service_pools(service_rows)
    licensing_inputs=default_licensing()
    licensing_inputs.update(profile.get('licensing',{}))
    licensing=calculate_licensing(base,licensing_inputs)
    total_nodes=base['total_nodes']+(ds['total_nodes'] if ds else 0)+(kafka['workers'] if kafka else 0)+(kudu['workers'] if kudu else 0)+dedicated['total_nodes']
    return {'base':base,'data_services':ds,'kafka':kafka,'kudu':kudu,'dedicated_services':dedicated,'licensing':licensing,'capacity_percent':capacity_percent,'total_nodes':total_nodes}


def calculate_sensitivity(profile, change_percent, include_ds=True):
    _finite_number(change_percent, 'Sensitivity change')
    if not 0 <= change_percent <= 100:
        raise ValueError('Sensitivity change must be between 0 and 100%')

    multiplier = 1 + change_percent / 100
    scenarios = [
        ('Baseline', 1, 1),
        (f'Data +{change_percent:g}%', multiplier, 1),
        (f'Peak compute +{change_percent:g}%', 1, multiplier),
        (f'Data +{change_percent:g}% & peak compute +{change_percent:g}%', multiplier, multiplier),
    ]
    results = []
    for name, data_multiplier, compute_multiplier in scenarios:
        scenario_profile = deepcopy(profile)
        scenario_base = scenario_profile['base']
        for key in ('initial_tb', 'daily_gb'):
            scenario_base[key] *= data_multiplier
        for key in ('peak_vcores', 'peak_ram'):
            scenario_base[key] *= compute_multiplier
        for row in scenario_profile.get('data_classes',[]):
            if data_multiplier != 1:
                for key in ('Initial raw data (TB)','Daily ingest (GB/day)','Audit/log growth (TB/year)'):
                    row[key]*=data_multiplier
            if compute_multiplier != 1:
                row['Concurrent queries']=ceil(row['Concurrent queries']*compute_multiplier)
        result = calculate_environment(scenario_profile, include_ds=include_ds)
        results.append({
            'Scenario': name,
            'Change to raw data and ingest': f'{(data_multiplier - 1) * 100:g}%',
            'Change to peak CPU and RAM': f'{(compute_multiplier - 1) * 100:g}%',
            'Base workers': result['base']['workers'],
            'Base sizing driver': result['base']['driver'],
            'Required raw disk (TB)': result['base']['required_disk_tb'],
            'Installed raw disk (TB)': result['base']['installed_tb'],
            'Data Services workers (held constant)': result['data_services']['workers'] if result['data_services'] else 'Not calculated',
            'Total nodes in this cluster': result['total_nodes'],
        })
    return results
