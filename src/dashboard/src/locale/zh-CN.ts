import tips from './zh-CN/tips'
import jobV2 from './zh-CN/pages/jobV2/jobV2'
import jobs from './zh-CN/pages/jobs/jobs'
import hooks from './zh-CN/hooks/hooks'
import components from './zh-CN/components/components'
import layout from './zh-CN/layout/layout'
import home from './zh-CN/pages/Home/home'
import submission from './zh-CN/pages/Submission/submission'
import jobsV2 from './zh-CN/pages/jobsV2/jobsV2'
import ClusterStatus from './zh-CN/ClusterStatus';
import VirtualCluster from './zh-CN/VirtualCluster';
import model from './zh-CN/model'
import version from './zh-CN/version';
import teams from './zh-CN/teams';

export default {
  tips,
  jobs,
  jobV2,
  hooks,
  components,
  layout,
  home,
  submission,
  jobsV2,
  ...ClusterStatus,
  ...VirtualCluster,
  ...model,
  ...version,
  copy: '复制',
  teams,
}