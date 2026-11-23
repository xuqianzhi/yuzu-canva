// The app's language: English or Chinese, picked in the landing page's Settings.
//
// The choice is saved on the backend (it also words every prompt the
// backend writes for the models) and cached in localStorage, so the UI
// starts in the last language picked without waiting for the server.
//
// Components call `useT()` and re-render when the language changes; code
// outside components (store notices) calls `t()` at the time it runs.
import { useMemo } from "react";
import { create } from "zustand";
import { api, ApiError, unwrap } from "./api/client";

export type Language = "en" | "zh";

export const LANGUAGES: { code: Language; label: string }[] = [
  { code: "en", label: "English" },
  { code: "zh", label: "中文" },
];

const en = {
  // --- landing page ---
  main_menu: "Main menu",
  nav_projects: "Projects",
  nav_defaults: "Defaults",
  nav_defaults_hint: "Every new project starts with these",
  nav_assets: "Assets",
  nav_assets_hint: "Global assets: every new project starts with these",
  nav_instruction: "Instruction",
  nav_instruction_hint: "Global instruction: every new project starts with a copy",
  language: "Language",
  projects_title: "Projects",
  projects_help: "Each project is one canvas. Everything saves automatically.",
  loading: "Loading…",
  projects_load_error: "Can't load projects: {error}. Is the backend running?",
  project_delete_confirm:
    "Delete project “{name}”?\n\nIts nodes, prompts{outputs} will be permanently deleted. This can't be undone.",
  project_delete_outputs_one: " and its {n} generated file",
  project_delete_outputs_other: " and its {n} generated files",
  delete_failed: "Can't delete it: {error}",
  delete: "Delete",
  delete_project_aria: "Delete project {name}",
  count_node_one: "{n} node",
  count_node_other: "{n} nodes",
  count_image_one: "{n} image",
  count_image_other: "{n} images",
  count_video_one: "{n} video",
  count_video_other: "{n} videos",
  count_running: "{n} running",
  edited_when: "Edited {when}",
  time_just_now: "just now",
  time_min: "{n} min ago",
  time_hours: "{n} h ago",
  time_days_one: "{n} day ago",
  time_days_other: "{n} days ago",
  new_project: "New project",
  project_name: "Project name",
  project_name_placeholder: "e.g. Fox in the snow",
  create: "Create",
  cancel: "Cancel",
  create_failed: "Can't create the project: {error}",
  ga_title: "Global assets",
  ga_help:
    "Every new project starts with these as nodes, down the left side of its canvas. Each gets an ID from its file name; click it to change it (it becomes the node's ID).",
  upload: "Upload",
  uploading: "Uploading…",
  ga_empty: "Drop images or videos here, or click to upload",
  ga_drop: "Drop to add global assets",
  ga_id_aria: "Global asset ID",
  ga_delete_aria: "Delete global asset {name}",
  ga_delete_title: "Delete (projects already made keep it)",
  ga_delete_confirm:
    "Delete global asset “{name}”?\n\nNew projects won't start with it any more. Projects already made keep their copy.",
  ga_load_error: "Can't load global assets: {error}",
  upload_failed: "Couldn't upload {list}",
  ga_needs_id: "A global asset needs an ID.",
  id_taken: "“{id}” is already taken.",
  video_seconds: "Video · {n}s",
  gi_title: "Global instruction",
  gi_help:
    "Standing guidance, like a project's custom instructions. Every new project starts with a copy, which it can then change on its own.",
  gi_placeholder:
    "e.g. Soft pastel palette, children's picture-book style, characters always smiling…",
  saved: "Saved",
  saving: "Saving…",
  edited: "Edited",
  save_error: "Can't save: {error}",
  load_error: "Can't load it: {error}",

  // --- project shell ---
  open_error: "Can't open this project.",
  back_to_projects: "Back to projects",
  back: "← Projects",
  undo_title: "Undo ({key})",
  redo_title: "Redo ({key})",
  undo: "Undo",
  redo: "Redo",

  // --- canvas menu ---
  canvas_menu: "Canvas menu",
  nav_nodes: "Nodes",
  assets_help: "Images (PNG, JPEG, WebP) and videos (MP4, MOV). Drag one onto the canvas to make it a node.",
  uploading_files_one: "Uploading {n} file…",
  uploading_files_other: "Uploading {n} files…",
  assets_empty: "Drop files here or click to upload",
  drop_to_upload: "Drop to upload",
  material_title: "{name} — drag onto the canvas",
  material_remove_aria: "Remove {name} from assets",
  material_remove_title: "Remove from assets (nodes made from it stay)",
  nodes_help:
    "IDs are optional and unique in this canvas; a node needs one before others can use it. Click a row to find the node.",
  nodes_empty: "No nodes yet. Double-click the canvas to add one.",
  kind_image: "image",
  kind_video: "video",
  kind_text: "text",
  kind_uploaded: "uploaded {kind}",
  project_instruction_help:
    "Standing guidance for this project. It started as a copy of the global instruction; changes here only affect this project.",
  project_instruction_aria: "Project instruction",
  project_instruction_placeholder: "e.g. Soft pastel palette, children's picture-book style…",

  // --- nodes ---
  add_id: "Add an ID",
  node_id_aria: "Node ID",
  node_kind: "Node kind",
  shape_image: "Image",
  shape_video: "Video",
  shape_text: "Text",
  needs_id_hint: "Give this node an ID to use its output elsewhere",
  node_ids_aria: "Node IDs",
  mention_none: "No node with that ID",
  mention_no_ids: "No other node has an ID yet",
  drop_input: "Drop a connection here to use another node's output",
  drag_output: "Drag to another node to use this output there",
  drag_file: "Drag to another node to use this file there",
  drag_to_move: "Drag to move",
  open_step: "Open the {step} step",
  inputs_aria: "Inputs",
  loop_warning: "{ids} isn't linked: it would make a loop.",
  ph_describe: "Describe the {kind}… type @ to pick another node",
  size: "Size",
  size_auto: "Size: auto",
  quality: "Quality",
  quality_auto: "Quality: auto",
  quality_low: "low",
  quality_medium: "medium",
  quality_high: "high",
  ratio: "Ratio",
  duration: "Duration",
  seconds: "{n}s",
  resolution: "Resolution",
  audio: "Audio",
  audio_title: "Generate a soundtrack",
  text_output: "Text output",
  delete_node: "Delete node",
  generate: "Generate",
  generate_title: "Generate (⌘↵)",
  write_prompt_first: "Write a prompt first",
  untitled_node: "Untitled node",
  no_output_suffix: " (no output yet)",
  no_output: "No output yet",
  queued: "Queued…",
  generating: "Generating…",
  videos_take_minutes: "Videos usually take a few minutes.",
  uploaded_kind: "Uploaded {kind}",
  uploaded_hint_video: "Connect its output into a video node to use it there.",
  uploaded_hint_image: "Connect its output into an image or video node to use it there.",

  // --- canvas ---
  selection_aria: "Selection",
  selected: "{parts} selected",
  count_connection_one: "{n} connection",
  count_connection_other: "{n} connections",
  list_sep: ", ",
  canvas_hint: "Drag on empty space to select · move the view with the map (bottom right)",
  canvas_empty: "Double-click anywhere to add a node, or drag in assets from the left.",
  create_menu_aria: "Create a connected node",
  menu_from_output: "Use this output in a new…",
  menu_feed_input: "Feed this input from a new…",
  map_aria: "Map: drag to move the view",

  // --- notices ---
  give_id_first: "Give that node an ID first: nothing can refer to a node without one.",
  loop_or_exists: "That connection would make a loop or already exists.",
  input_no_output: "“{label}” has no output yet. Generate it first.",
  undo_failed: "Couldn't undo {label}: {error}",
  redo_failed: "Couldn't redo {label}: {error}",
  h_prompt: "the prompt edit",
  h_connection: "the connection",
  h_add: "adding the node",
  h_kind: "the kind change",
  h_settings: "the settings change",
  h_delete: "the delete",
  h_move: "the move",
  h_move_many: "moving the nodes",
  h_id: "the ID change",
  deleted_too_long: "it was deleted too long ago to bring back",
  node_gone: "That node no longer exists.",
  workflow_cant_delete: "Workflow nodes belong to their step and can't be deleted.",
  workflow_skipped: "Skipped the workflow nodes: they belong to their step.",
  delete_failed_notice: "Couldn't delete: {error}",
  deleted_notice: "Deleted {parts} · {key} to undo",
  join_and: " and ",
  id_clash: "Another node already has the ID “{id}”.",
  add_failed: "Couldn't add it: {error}",
  id_rule: "IDs can use letters, numbers, _ and - (no spaces).",

  // --- workflow ---
  wf_aria: "Workflow",
  st_ready: "Ready to start",
  st_in_progress: "In progress",
  pill_ready: "Not started",
  pill_in_progress: "In progress",
  step_of: "Step {n} of {total}",
  close_panel: "Close the step panel",
  close: "Close",
  step_panel_aria: "{step} step",
  start_per_item:
    "Starting this step adds one {item} node per approved {input_item}, connected to the step before.",
  start_split:
    "Starting this step adds one {item} node per {item} in the {input}, connected to the step before.",
  ph_shot: "Describe the shot… type @ to pick a node",
  generate_again: "Generate again",
  versions_aria: "Versions",
  prev_version: "Previous version",
  next_version: "Next version",
  version_of: "Version {n} of {total}",
  edit_version_aria: "Edit this version",
  save_new_version: "Save as new version",
  edit: "Edit",
  go_to_arrow: "Go to {step} →",
  chat_title: "Iterate with AI",
  chat_thinking: "Thinking…",
  chat_empty: "Ask for changes and get a new version to apply, without leaving the canvas.",
  chat_placeholder: "e.g. Make the ending sadder",
  message_aria: "Message",
  send: "Send",
  suggested_version: "Suggested version",
  applied: "✓ Applied as a new version",
  apply: "Apply as new version",

  // --- workflow runs ---
  run_prompt: "Prompt",
  run_prompt_ph: "What should this step make?",
  run_count: "How many",
  run_go: "Generate {n}",
  run_again: "Generate {n} again",
  run_replace: "Generating again replaces this step's {n} nodes. Continue?",
  run_uses_previous: "One per result of “{step}” ({n}), each made from its own result.",
  run_uses_instruction: "Sent with the project instruction. Type a node's ID (like {example}) to use its output.",
  run_media_note: "The AI writes one prompt per node; each is generated right away.",
  run_direct_note: "Each result of “{step}” is used as its node's prompt; anything here is added to every one.",
  run_direction: "Extra direction (optional)",
  wf_output: "Results are",
  wf_output_independent: "Independent",
  wf_output_one_to_one: "One-to-one into the next step (no ID)",
  wf_output_last: "The last step's results are independent.",
  pill_done: "Done",
  wf_name_ph: "Workflow name",
  generate_all_confirm: "Generate {n} videos? Each one is a paid Seedance job.",
  label_prompt: "Prompt",
  nav_workflows: "Workflows",
  nav_workflows_hint: "Workflows: the steps every new project goes through",
  nav_settings: "Settings",
  settings_title: "Settings",
  settings_language_help: "The language of the app, and of the prompts it writes for the AI models. What you type is never translated.",
  new_project_workflow: "Workflow",

  // --- workflow designer ---
  wf_title: "Workflows",
  wf_help: "Design the steps a project goes through. New projects copy the default workflow; projects keep the version they started with.",
  wf_new: "New workflow",
  wf_duplicate: "Duplicate",
  wf_default: "Default",
  wf_make_default: "Make default",
  wf_save: "Save",
  wf_unsaved: "Unsaved changes",
  wf_name: "Name",
  wf_version: "Version {n}",
  wf_add_step: "Add step",
  wf_move_up: "Move up",
  wf_move_down: "Move down",
  wf_remove_step: "Remove step",
  wf_step_name: "Step name",
  wf_kind: "Makes",
  wf_confirm_delete: "Delete workflow “{name}”? Projects that use it keep their copy.",
  wf_copy: "{name} (copy)",
  wf_new_name: "New workflow",
  wf_new_step: "New step",
  wf_empty: "No workflow selected.",

  // --- API errors, by code (English shows the server's own message) ---
  err_workflow_blocked: "Approve the step before first.",
  err_workflow_locked: "Workflow nodes and connections belong to the workflow.",
  err_duplicate_name: "Another node already has this ID.",
  err_cycle: "That would make a loop.",
  err_no_id: "Give this node an ID first.",
  err_missing_ref_output: "An input has no output yet; generate it first.",
  err_unsupported_ref: "This kind of input can't be used here.",
  err_too_many_refs: "Too many inputs of one kind.",
  err_job_in_progress: "This node is already generating.",
  err_provider_error: "The model service failed: {message}",
  err_not_generatable: "This node can't generate.",
  err_validation_error: "Invalid: {message}",
  err_not_found: "Not found; it may have been deleted.",
  err_unsupported_media: "Unsupported file: use PNG, JPEG, WebP, MP4 or MOV.",
  err_too_large: "That file is too big.",
  err_self_reference: "A node can't refer to itself.",
  err_duplicate_edge: "That connection already exists.",
  err_job_finished: "That job already finished.",
  err_unknown_mention: "The prompt mentions a node that isn't connected.",
  err_not_implemented: "Not available yet.",
  err_unauthenticated: "Your sign-in expired; sign in again.",
  err_forbidden: "This account doesn't have access.",
  err_quota_exceeded: "Limit reached: {message}",
  err_generation_off: "Generation is turned off for now; try later.",
  // --- sign-in and account ---
  signin_help: "Sign in to open your projects.",
  signin_google: "Sign in with Google",
  signin_email_ph: "Your email",
  signin_dev: "Sign in",
  signin_dev_note: "Local development: no password. The deployed app uses Google sign-in.",
  noaccess_title: "No access yet",
  noaccess_help: "{email} isn't on this app's list of users. Ask the owner to add you, or sign in with another account.",
  sign_out: "Sign out",
  try_again: "Try again",
  account: "Account",
  account_help: "Signed in as {email}.",
  usage_title: "Today's usage",
  usage_help: "Counted per day (UTC). Limits keep the model costs in check.",
  usage_text: "Text calls",
  usage_image: "Images",
  usage_video: "Videos",
  usage_of: "{used} of {limit}",
  usage_unlimited: "{used} (no limit)",
  run_failed: "The run failed; try again.",
  keep_open: "Generating: keep this page open until it's done.",
};

export type Key = keyof typeof en;

const zh: Record<Key, string> = {
  main_menu: "主菜单",
  nav_projects: "项目",
  nav_defaults: "默认",
  nav_defaults_hint: "每个新项目都以这些开始",
  nav_assets: "素材",
  nav_assets_hint: "全局素材：每个新项目都以这些开始",
  nav_instruction: "指令",
  nav_instruction_hint: "全局指令：每个新项目都会得到一份副本",
  language: "语言",
  projects_title: "项目",
  projects_help: "每个项目是一块画布。所有内容都会自动保存。",
  loading: "加载中…",
  projects_load_error: "无法加载项目：{error}。后端在运行吗？",
  project_delete_confirm: "删除项目“{name}”？\n\n它的节点、提示词{outputs}将被永久删除，且无法撤销。",
  project_delete_outputs_one: "以及它生成的 {n} 个文件",
  project_delete_outputs_other: "以及它生成的 {n} 个文件",
  delete_failed: "无法删除：{error}",
  delete: "删除",
  delete_project_aria: "删除项目 {name}",
  count_node_one: "{n} 个节点",
  count_node_other: "{n} 个节点",
  count_image_one: "{n} 张图片",
  count_image_other: "{n} 张图片",
  count_video_one: "{n} 个视频",
  count_video_other: "{n} 个视频",
  count_running: "{n} 个进行中",
  edited_when: "编辑于{when}",
  time_just_now: "刚刚",
  time_min: "{n} 分钟前",
  time_hours: "{n} 小时前",
  time_days_one: "{n} 天前",
  time_days_other: "{n} 天前",
  new_project: "新建项目",
  project_name: "项目名称",
  project_name_placeholder: "例如：雪中的狐狸",
  create: "创建",
  cancel: "取消",
  create_failed: "无法创建项目：{error}",
  ga_title: "全局素材",
  ga_help:
    "每个新项目都会把它们作为节点，排在画布左侧。每个素材的 ID 取自文件名；点击即可修改（它会成为节点的 ID）。",
  upload: "上传",
  uploading: "上传中…",
  ga_empty: "把图片或视频拖到这里，或点击上传",
  ga_drop: "松开即可添加全局素材",
  ga_id_aria: "全局素材 ID",
  ga_delete_aria: "删除全局素材 {name}",
  ga_delete_title: "删除（已创建的项目会保留它）",
  ga_delete_confirm: "删除全局素材“{name}”？\n\n新项目将不再包含它，已创建的项目会保留各自的副本。",
  ga_load_error: "无法加载全局素材：{error}",
  upload_failed: "无法上传 {list}",
  ga_needs_id: "全局素材需要一个 ID。",
  id_taken: "“{id}”已被使用。",
  video_seconds: "视频 · {n} 秒",
  gi_title: "全局指令",
  gi_help: "长期有效的指导，类似项目的自定义指令。每个新项目都会得到一份副本，之后可以单独修改。",
  gi_placeholder: "例如：柔和的马卡龙色调、儿童绘本风格、角色总是面带微笑……",
  saved: "已保存",
  saving: "保存中…",
  edited: "已编辑",
  save_error: "无法保存：{error}",
  load_error: "无法加载：{error}",

  open_error: "无法打开这个项目。",
  back_to_projects: "返回项目列表",
  back: "← 项目",
  undo_title: "撤销（{key}）",
  redo_title: "重做（{key}）",
  undo: "撤销",
  redo: "重做",

  canvas_menu: "画布菜单",
  nav_nodes: "节点",
  assets_help: "图片（PNG、JPEG、WebP）和视频（MP4、MOV）。把它拖到画布上即可成为节点。",
  uploading_files_one: "正在上传 {n} 个文件…",
  uploading_files_other: "正在上传 {n} 个文件…",
  assets_empty: "把文件拖到这里，或点击上传",
  drop_to_upload: "松开即可上传",
  material_title: "{name} —— 拖到画布上",
  material_remove_aria: "从素材中移除 {name}",
  material_remove_title: "从素材中移除（用它创建的节点会保留）",
  nodes_help: "ID 可选，且在画布中唯一；节点需要有 ID 才能被其他节点使用。点击一行即可定位节点。",
  nodes_empty: "还没有节点。双击画布即可添加。",
  kind_image: "图片",
  kind_video: "视频",
  kind_text: "文本",
  kind_uploaded: "上传的{kind}",
  project_instruction_help: "这个项目的长期指导。它最初复制自全局指令；在这里的修改只影响本项目。",
  project_instruction_aria: "项目指令",
  project_instruction_placeholder: "例如：柔和的马卡龙色调、儿童绘本风格……",

  add_id: "添加 ID",
  node_id_aria: "节点 ID",
  node_kind: "节点类型",
  shape_image: "图片",
  shape_video: "视频",
  shape_text: "文本",
  needs_id_hint: "给这个节点一个 ID，才能在别处使用它的输出",
  node_ids_aria: "节点 ID",
  mention_none: "没有这个 ID 的节点",
  mention_no_ids: "还没有其他节点有 ID",
  drop_input: "把连线拖到这里，使用另一个节点的输出",
  drag_output: "拖到另一个节点上，在那里使用这个输出",
  drag_file: "拖到另一个节点上，在那里使用这个文件",
  drag_to_move: "拖动以移动",
  open_step: "打开“{step}”步骤",
  inputs_aria: "输入",
  loop_warning: "{ids} 未链接：会形成循环。",
  ph_describe: "描述这个{kind}……输入 @ 选择其他节点",
  size: "尺寸",
  size_auto: "尺寸：自动",
  quality: "质量",
  quality_auto: "质量：自动",
  quality_low: "低",
  quality_medium: "中",
  quality_high: "高",
  ratio: "比例",
  duration: "时长",
  seconds: "{n} 秒",
  resolution: "分辨率",
  audio: "音频",
  audio_title: "生成配乐",
  text_output: "文本输出",
  delete_node: "删除节点",
  generate: "生成",
  generate_title: "生成（⌘↵）",
  write_prompt_first: "请先写提示词",
  untitled_node: "未命名节点",
  no_output_suffix: "（尚无输出）",
  no_output: "尚无输出",
  queued: "排队中…",
  generating: "生成中…",
  videos_take_minutes: "视频通常需要几分钟。",
  uploaded_kind: "上传的{kind}",
  uploaded_hint_video: "把它的输出连接到视频节点即可使用。",
  uploaded_hint_image: "把它的输出连接到图片或视频节点即可使用。",

  selection_aria: "选择",
  selected: "已选择{parts}",
  count_connection_one: "{n} 条连线",
  count_connection_other: "{n} 条连线",
  list_sep: "、",
  canvas_hint: "在空白处拖动以选择 · 用右下角的小地图移动视图",
  canvas_empty: "双击任意位置添加节点，或从左侧拖入素材。",
  create_menu_aria: "创建相连的节点",
  menu_from_output: "在新的……中使用这个输出",
  menu_feed_input: "用新的……作为这个输入",
  map_aria: "小地图：拖动以移动视图",

  give_id_first: "请先给那个节点一个 ID：没有 ID 的节点无法被引用。",
  loop_or_exists: "这条连线会形成循环，或已经存在。",
  input_no_output: "“{label}”还没有输出。请先生成它。",
  undo_failed: "无法撤销{label}：{error}",
  redo_failed: "无法重做{label}：{error}",
  h_prompt: "提示词修改",
  h_connection: "连线",
  h_add: "添加节点",
  h_kind: "类型更改",
  h_settings: "设置更改",
  h_delete: "删除",
  h_move: "移动",
  h_move_many: "移动节点",
  h_id: "ID 修改",
  deleted_too_long: "删除时间过久，无法恢复",
  node_gone: "那个节点已不存在。",
  workflow_cant_delete: "工作流节点属于各自的步骤，不能删除。",
  workflow_skipped: "已跳过工作流节点：它们属于各自的步骤。",
  delete_failed_notice: "无法删除：{error}",
  deleted_notice: "已删除{parts} · 按 {key} 撤销",
  join_and: "和",
  id_clash: "另一个节点已经使用了 ID“{id}”。",
  add_failed: "无法添加：{error}",
  id_rule: "ID 只能使用字母、数字、_ 和 -（不能有空格）。",

  wf_aria: "工作流",
  st_ready: "可以开始",
  st_in_progress: "进行中",
  pill_ready: "未开始",
  pill_in_progress: "进行中",
  step_of: "第 {n} 步，共 {total} 步",
  close_panel: "关闭步骤面板",
  close: "关闭",
  step_panel_aria: "“{step}”步骤",
  start_per_item: "开始这一步会为每个已确认的{input_item}添加一个{item}节点，并连接到上一步。",
  start_split: "开始这一步会为{input}中的每个{item}添加一个{item}节点，并连接到上一步。",
  ph_shot: "描述这个镜头……输入 @ 选择节点",
  generate_again: "再次生成",
  versions_aria: "版本",
  prev_version: "上一个版本",
  next_version: "下一个版本",
  version_of: "第 {n} 版，共 {total} 版",
  edit_version_aria: "编辑这个版本",
  save_new_version: "另存为新版本",
  edit: "编辑",
  go_to_arrow: "前往{step} →",
  chat_title: "与 AI 迭代",
  chat_thinking: "思考中…",
  chat_empty: "提出修改要求，得到可以直接采用的新版本，无需离开画布。",
  chat_placeholder: "例如：让结局更悲伤一些",
  message_aria: "消息",
  send: "发送",
  suggested_version: "建议的版本",
  applied: "✓ 已作为新版本采用",
  apply: "作为新版本采用",

  run_prompt: "提示词",
  run_prompt_ph: "这一步要生成什么？",
  run_count: "数量",
  run_go: "生成 {n} 个",
  run_again: "重新生成 {n} 个",
  run_replace: "重新生成会替换这一步的 {n} 个节点。继续吗？",
  run_uses_previous: "“{step}”的每个结果对应一个（共 {n} 个），各自由对应的结果生成。",
  run_uses_instruction: "会连同项目指令一起发送。输入节点 ID（例如 {example}）即可使用它的输出。",
  run_media_note: "AI 会为每个节点写一条提示词，并立即生成。",
  run_direct_note: "“{step}”的每个结果会直接作为对应节点的提示词；这里填写的内容会加到每一条后面。",
  run_direction: "补充方向（可选）",
  wf_output: "结果用法",
  wf_output_independent: "独立",
  wf_output_one_to_one: "一对一传给下一步（无 ID）",
  wf_output_last: "最后一步的结果是独立的。",
  pill_done: "完成",
  wf_name_ph: "工作流名称",
  generate_all_confirm: "生成 {n} 个视频？每个都是付费的 Seedance 任务。",
  label_prompt: "提示词",
  nav_workflows: "工作流",
  nav_workflows_hint: "工作流：每个新项目要经过的步骤",
  nav_settings: "设置",
  settings_title: "设置",
  settings_language_help: "应用的语言，以及它为 AI 模型撰写的提示词的语言。你输入的内容不会被翻译。",
  new_project_workflow: "工作流",

  wf_title: "工作流",
  wf_help: "设计项目要经过的步骤。新项目会复制默认工作流；项目会保留创建时的版本。",
  wf_new: "新建工作流",
  wf_duplicate: "复制",
  wf_default: "默认",
  wf_make_default: "设为默认",
  wf_save: "保存",
  wf_unsaved: "有未保存的更改",
  wf_name: "名称",
  wf_version: "版本 {n}",
  wf_add_step: "添加步骤",
  wf_move_up: "上移",
  wf_move_down: "下移",
  wf_remove_step: "删除步骤",
  wf_step_name: "步骤名称",
  wf_kind: "生成",
  wf_confirm_delete: "删除工作流“{name}”？使用它的项目会保留各自的副本。",
  wf_copy: "{name}（副本）",
  wf_new_name: "新工作流",
  wf_new_step: "新步骤",
  wf_empty: "没有选中的工作流。",

  err_workflow_blocked: "请先确认上一步。",
  err_workflow_locked: "工作流的节点和连线属于工作流，不能这样修改。",
  err_duplicate_name: "另一个节点已经使用了这个 ID。",
  err_cycle: "这会形成循环。",
  err_no_id: "请先给这个节点一个 ID。",
  err_missing_ref_output: "某个输入还没有输出，请先生成它。",
  err_unsupported_ref: "这里不能使用这种输入。",
  err_too_many_refs: "同一类型的输入太多了。",
  err_job_in_progress: "这个节点正在生成中。",
  err_provider_error: "模型服务出错：{message}",
  err_not_generatable: "这个节点不能生成。",
  err_validation_error: "无效：{message}",
  err_not_found: "找不到，可能已被删除。",
  err_unsupported_media: "不支持的文件：请使用 PNG、JPEG、WebP、MP4 或 MOV。",
  err_too_large: "文件太大。",
  err_self_reference: "节点不能引用自身。",
  err_duplicate_edge: "这条连线已经存在。",
  err_job_finished: "这个任务已经结束。",
  err_unknown_mention: "提示词提到了一个未连接的节点。",
  err_not_implemented: "暂不支持。",
  err_unauthenticated: "登录已过期，请重新登录。",
  err_forbidden: "这个账号没有访问权限。",
  err_quota_exceeded: "已达到上限：{message}",
  err_generation_off: "生成功能暂时关闭，请稍后再试。",
  // --- sign-in and account ---
  signin_help: "登录以打开你的项目。",
  signin_google: "使用 Google 登录",
  signin_email_ph: "你的邮箱",
  signin_dev: "登录",
  signin_dev_note: "本地开发：无需密码。部署后的应用使用 Google 登录。",
  noaccess_title: "暂无访问权限",
  noaccess_help: "{email} 不在这个应用的用户名单里。请联系所有者添加你，或换一个账号登录。",
  sign_out: "退出登录",
  try_again: "重试",
  account: "账号",
  account_help: "当前登录：{email}。",
  usage_title: "今日用量",
  usage_help: "按天计算（UTC）。上限用来控制模型费用。",
  usage_text: "文本调用",
  usage_image: "图片",
  usage_video: "视频",
  usage_of: "{used} / {limit}",
  usage_unlimited: "{used}（无上限）",
  run_failed: "运行失败，请重试。",
  keep_open: "正在生成：请保持此页面打开，直到完成。",
};

const DICTS: Record<Language, Record<Key, string>> = { en, zh };
const STORAGE_KEY = "seedance-canvas.language";

export type Vars = Record<string, string | number>;

function format(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

function translate(language: Language, key: Key, vars?: Vars): string {
  return format(DICTS[language][key] ?? en[key], vars);
}

function stored(): Language {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "en" || value === "zh") return value;
  } catch {
    // storage unavailable: fall through
  }
  return navigator.language?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

interface LanguageState {
  language: Language;
  setLanguage(language: Language): void;
}

function apply(language: Language) {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  try {
    localStorage.setItem(STORAGE_KEY, language);
  } catch {
    // only a cache: the backend has the setting
  }
}

export const useLanguage = create<LanguageState>()((set) => ({
  language: stored(),
  setLanguage(language) {
    set({ language });
    apply(language);
    void api.PUT("/api/settings", { body: { language } }).catch(() => {});
  },
}));
apply(useLanguage.getState().language);

/** Take the backend's setting (the last choice) once at start-up. */
export async function loadLanguage(): Promise<void> {
  try {
    const settings = unwrap(await api.GET("/api/settings"));
    if (settings.language !== useLanguage.getState().language) {
      useLanguage.setState({ language: settings.language });
      apply(settings.language);
    }
  } catch {
    // keep the cached choice
  }
}

/** Translate now, in the current language (for code outside components). */
export function t(key: Key, vars?: Vars): string {
  return translate(useLanguage.getState().language, key, vars);
}

/** `key_one` or `key_other` by `n`, with {n} filled in. */
export function tn(base: string, n: number, vars?: Vars): string {
  return t(`${base}_${n === 1 ? "one" : "other"}` as Key, { n, ...vars });
}

export type T = ((key: Key, vars?: Vars) => string) & {
  n: (base: string, n: number, vars?: Vars) => string;
  language: Language;
};

/** A translator that re-renders the component when the language changes. */
export function useT(): T {
  const language = useLanguage((s) => s.language);
  return useMemo(
    () =>
      Object.assign((key: Key, vars?: Vars) => translate(language, key, vars), {
        n: (base: string, n: number, vars?: Vars) =>
          translate(language, `${base}_${n === 1 ? "one" : "other"}` as Key, { n, ...vars }),
        language,
      }),
    [language],
  );
}

/** Text given in several languages (workflow labels), in the current one. */
export function pick(text: Record<string, string> | undefined, language: Language): string {
  if (!text) return "";
  return text[language] || text.en || Object.values(text)[0] || "";
}

/** An error, for the UI: the API's message in English; in other languages
    the wording for its error code when there is one. */
export function errorText(error: unknown): string {
  const raw =
    error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);
  const language = useLanguage.getState().language;
  if (language === "en" || !(error instanceof ApiError)) return raw;
  const key = `err_${error.code}` as Key;
  return key in en ? translate(language, key, { message: raw }) : raw;
}
