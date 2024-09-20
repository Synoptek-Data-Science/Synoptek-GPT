import os
import json
import datetime
import logging  # For logging
import streamlit as st
from openai import AzureOpenAI
from dotenv import load_dotenv
import streamlit_authenticator as stauth
import pyotp
import qrcode
import io
from io import BytesIO
from azure.storage.blob import BlobServiceClient
from yaml.loader import SafeLoader
import yaml
import uuid  # Added for generating unique IDs

# Load environment variables
load_dotenv()

# Set up logging to display on the command line
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Azure OpenAI configuration
azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

st.set_page_config(
    page_title="SynoptekGPT",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto"
)

# Initialize the Azure OpenAI client with error handling
try:
    client = AzureOpenAI(
        api_key=azure_openai_api_key,
        azure_endpoint=azure_endpoint,
        api_version="2024-04-01-preview",
    )
except Exception as e:
    st.error("Failed to initialize Azure OpenAI client.")
    logging.error(f"OpenAI Client Initialization Error: {e}")
    st.stop()

# Load config from Azure Blob Storage
connection_string = os.getenv("BLOB_CONNECTION_STRING")
container_name = "itgluecopilot"
config_blob_name = "config/config_quad.yaml"

# BlobServiceClient
blob_service_client = BlobServiceClient.from_connection_string(connection_string)
container_client = blob_service_client.get_container_client(container_name)

# Load the YAML configuration file
blob_client = container_client.get_blob_client(config_blob_name)
blob_data = blob_client.download_blob().readall()
config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# Initialize the authenticator
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
)

# Function to handle user authentication
def authenticate_user(authentication_status, name, username):
    if authentication_status:
        st.session_state["authentication_status"] = True
        st.session_state["name"] = name
        st.session_state["username"] = username

        user_data = config['credentials']['usernames'][username]
        user_role = user_data.get('role', 'viewer')
        st.session_state['user_role'] = user_role

        otp_secret = user_data.get('otp_secret', "")

        if not otp_secret:
            otp_secret = pyotp.random_base32()
            config['credentials']['usernames'][username]['otp_secret'] = otp_secret
            blob_client.upload_blob(yaml.dump(config), overwrite=True)
            st.session_state['otp_setup_complete'] = False
            st.session_state['show_qr_code'] = True
            logging.info("Generated new OTP secret for user %s", username)
        else:
            st.session_state['otp_setup_complete'] = True

        totp = pyotp.TOTP(otp_secret)
        logging.info("Using OTP secret for user %s", username)

        if not st.session_state.get('otp_verified', False):
            if st.session_state.get('show_qr_code', False):
                st.title("Welcome! 👋")
                otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoGPT")
                qr = qrcode.make(otp_uri)
                qr = qr.resize((200, 200))
                st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: Google Authenticator)")

            st.title("Welcome to SynoptekGPT!")
            otp_input = st.text_input("Enter the OTP from your authenticator app", type="password", key='otp_input')
            verify_button_clicked = st.button("Verify OTP", key='verify_otp_button')

            if verify_button_clicked:
                if totp.verify(otp_input):
                    st.session_state['otp_verified'] = True
                    st.session_state['show_qr_code'] = False
                    message_placeholder = st.empty()
                    message_id = str(uuid.uuid4()).replace('-', '')
                    message_html = f'''
                    <div id="{message_id}">
                        <p style="color:green; font-weight:bold;">Welcome back, {name}!</p>
                    </div>
                    <script>
                    setTimeout(function() {{
                        var elem = document.getElementById('{message_id}');
                        if(elem) {{
                            elem.parentNode.removeChild(elem);
                        }}
                    }}, 5000);
                    </script>
                    '''
                    message_placeholder.markdown(message_html, unsafe_allow_html=True)
                    logging.info("User %s authenticated successfully with 2FA", username)
                    return True
                else:
                    st.error("Invalid OTP. Please try again.")
                    logging.warning("Invalid OTP attempt for user %s", username)
                    return False
        else:
            if not st.session_state.get('welcome_message_displayed', False):
                message_placeholder = st.empty()
                message_id = str(uuid.uuid4()).replace('-', '')
                message_html = f'''
                <div id="{message_id}">
                    <p style="color:green; font-weight:bold;">Welcome back, {name}!</p>
                </div>
                <script>
                setTimeout(function() {{
                    var elem = document.getElementById('{message_id}');
                    if(elem) {{
                        elem.parentNode.removeChild(elem);
                    }}
                }}, 5000);
                </script>
                '''
                message_placeholder.markdown(message_html, unsafe_allow_html=True)
                st.session_state['welcome_message_displayed'] = True
            logging.info("User %s re-authenticated successfully", username)
            return True

    elif authentication_status == False:
        st.write("# Welcome! 👋")
        st.markdown("Please enter your username and password to log in.")
        logging.warning("Failed login attempt with username: %s", username)
        return False

    elif authentication_status == None:
        st.write("# Welcome! 👋")
        st.markdown("Please enter your username and password to log in.")
        return False

# Sidebar code
with st.sidebar:
    st.image(r"./synoptek.png", width=275)
    name, authentication_status, username = authenticator.login('Login', 'sidebar')

    if authentication_status and st.session_state.get('otp_verified', False):
        st.title("Conversations")

        if st.button("New Chat", key='new_chat_button'):
            st.session_state.messages = []

        # def load_conversations():
        #     try:
        #         blob_client = blob_service_client.get_blob_client(container="test-container", blob="conversations.json")
        #         blob_data = blob_client.download_blob().readall()
        #         return json.loads(blob_data)
        #     except Exception as e:
        #         st.error("Failed to load conversations.")
        #         logging.error(f"Load Conversations Error: {e}")
        #         return []

        def get_conversation_title(conversation):
            for msg in conversation["messages"]:
                if msg["role"] == "user":
                    title = msg["content"].strip()
                    return title[:28] + "..." if len(title) > 28 else title
            return "Untitled Conversation"

        def load_conversations():
            try:
                # Get the blob client for conversations.json
                blob_client = blob_service_client.get_blob_client(container="test-container", blob="conversations.json")
                
                # Check if the blob exists before trying to download
                if blob_client.exists():
                    # Download the blob data
                    blob_data = blob_client.download_blob().readall()
                    
                    # If blob data is empty, return an empty list
                    if not blob_data:
                        return []
                    
                    # Otherwise, return the parsed JSON data
                    return json.loads(blob_data)
                else:
                    # If the blob doesn't exist, return an empty list
                    return []
                
            except Exception as e:
                st.error("Failed to load conversations.")
                logging.error(f"Load Conversations Error: {e}")
                return []


        conversations = load_conversations()

        today, yesterday, previous_7_days, previous_30_days = [], [], [], []
        now = datetime.datetime.now()

        for idx, convo in enumerate(reversed(conversations)):
            try:
                timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
                delta = now - timestamp
                if delta.days == 0:
                    today.append((idx, convo))
                elif delta.days == 1:
                    yesterday.append((idx, convo))
                elif delta.days <= 7:
                    previous_7_days.append((idx, convo))
                elif delta.days <= 30:
                    previous_30_days.append((idx, convo))
            except Exception as e:
                logging.error(f"Error processing conversation timestamp: {e}")

        if today:
            st.subheader("Today")
            for idx, convo in today:
                title = get_conversation_title(convo)
                if st.button(title, key=f"today_{idx}"):
                    st.session_state.messages = convo["messages"]
                    st.rerun()

        if yesterday:
            st.subheader("Yesterday")
            for idx, convo in yesterday:
                title = get_conversation_title(convo)
                if st.button(title, key=f"yesterday_{idx}"):
                    st.session_state.messages = convo["messages"]
                    st.rerun()

        if previous_7_days:
            st.subheader("Previous 7 Days")
            for idx, convo in previous_7_days:
                title = get_conversation_title(convo)
                if st.button(title, key=f"week_{idx}"):
                    st.session_state.messages = convo["messages"]
                    st.rerun()

        if previous_30_days:
            st.subheader("Previous 30 Days")
            for idx, convo in previous_30_days:
                title = get_conversation_title(convo)
                if st.button(title, key=f"month_{idx}"):
                    st.session_state.messages = convo["messages"]
                    st.rerun()

        st.markdown("<br><br><br><br><br><br>", unsafe_allow_html=True)
        st.markdown("---")
        st.markdown(f'## Hello, *{name}*')

        if st.button("Logout", key='logout_button'):
            authenticator.logout('Logout', 'sidebar')
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    elif authentication_status == False:
        st.error('Username/password is incorrect')
    elif authentication_status == None:
        st.warning('Please enter your username and password')

# Call the authenticate_user function
if authenticate_user(authentication_status, name, username):
    st.title("Synoptek-GPT! 🤖")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "model" not in st.session_state:
        st.session_state.model = "gpt-4o"

    user_prompt = st.chat_input("Type here to Chat...")

    if user_prompt:
        st.session_state.messages.append({"role": "user", "content": user_prompt})

        for message in st.session_state.messages[:-1]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""

            try:
                stream = client.chat.completions.create(
                    model=st.session_state.model,
                    messages=st.session_state.messages,
                    stream=True,
                    max_tokens=4000,
                    temperature=0.2,
                )
                for chunk in stream:
                    choices = getattr(chunk, 'choices', None)
                    if choices:
                        choice = choices[0]
                        delta = getattr(choice, 'delta', None)
                        if delta:
                            token = getattr(delta, 'content', '')
                            if token:
                                full_response += token
                                message_placeholder.markdown(full_response + "▌")
                message_placeholder.markdown(full_response)
            except Exception as e:
                st.error("An error occurred while generating the response.")
                logging.error(f"API Error: {e}")
                full_response = "I'm sorry, but I'm unable to process your request at the moment."
                message_placeholder.markdown(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})

        def save_conversation(conversation):
            try:
                conversations = load_conversations()
                conversations.append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "messages": conversation
                })
                conversations = conversations[-30:]
                conversations_json = json.dumps(conversations, indent=4)
                blob_client = blob_service_client.get_blob_client(container="test-container", blob="conversations.json")
                blob_client.upload_blob(conversations_json, overwrite=True)
            except Exception as e:
                st.error("Failed to save conversation.")
                logging.error(f"Save Conversation Error: {e}")

        save_conversation(st.session_state.messages)

    else:
        if st.session_state.messages:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
        else:
            current_directory = os.path.dirname(os.path.abspath(__file__))
            image_path = os.path.join(current_directory, "chatbot.png") 
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                st.write("")
            with col2:
                st.image(image_path, width=375)
            with col3:
                st.write("")
            st.markdown(
                "<h4 style='text-align: center;'>Welcome to SynoptekGPT! Here you will be able to try out multiple models.</h4>",
                unsafe_allow_html=True
            )

else:
    st.stop()

































# # # # # # # # # # # # # # # # # import streamlit as st
# # # # # # # # # # # # # # # # # import os
# # # # # # # # # # # # # # # # # from dotenv import load_dotenv
# # # # # # # # # # # # # # # # # import openai  # Import the OpenAI library

# # # # # # # # # # # # # # # # # load_dotenv()

# # # # # # # # # # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # # # # # # # # # azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
# # # # # # # # # # # # # # # # # azure_endpoint = os.getenv("AZURE_ENDPOINT")

# # # # # # # # # # # # # # # # # # Set up Azure OpenAI credentials
# # # # # # # # # # # # # # # # # openai.api_type = "azure"
# # # # # # # # # # # # # # # # # openai.api_key = "OPENAI_API_KEY_AZURE"
# # # # # # # # # # # # # # # # # openai.api_base = "OPENAI_ENDPOINT_AZURE"  # This should be your Azure endpoint
# # # # # # # # # # # # # # # # # openai.api_version = "2024-04-01-preview"

# # # # # # # # # # # # # # # # # st.title("My Own ChatGPT! 🤖")

# # # # # # # # # # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # # # # # # # # # #     st.session_state.messages = []

# # # # # # # # # # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # # # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # # # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # # # # # # # # # Initialize model
# # # # # # # # # # # # # # # # # if "model" not in st.session_state:
# # # # # # # # # # # # # # # # #     st.session_state.model = "gpt-4o"  # Your Azure OpenAI deployment name

# # # # # # # # # # # # # # # # # # User input
# # # # # # # # # # # # # # # # # if user_prompt := st.chat_input("Your prompt"):
# # # # # # # # # # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # # # # # # # # # #     with st.chat_message("user"):
# # # # # # # # # # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # # # # # # # # # #     # Generate responses
# # # # # # # # # # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # # # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # # # # # # # # # #         full_response = ""

# # # # # # # # # # # # # # # # #         try:
# # # # # # # # # # # # # # # # #             # Use openai.ChatCompletion.create with Azure parameters
# # # # # # # # # # # # # # # # #             response = openai.ChatCompletion.create(
# # # # # # # # # # # # # # # # #                 engine=st.session_state.model,  # Use 'engine' for Azure
# # # # # # # # # # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # # # # # # # # # #                 max_tokens=4000,
# # # # # # # # # # # # # # # # #                 temperature=0.2,
# # # # # # # # # # # # # # # # #                 stream=True,
# # # # # # # # # # # # # # # # #             )

# # # # # # # # # # # # # # # # #             for chunk in response:
# # # # # # # # # # # # # # # # #                 token = chunk.choices[0].delta.get("content", "")
# # # # # # # # # # # # # # # # #                 if token:
# # # # # # # # # # # # # # # # #                     full_response += token
# # # # # # # # # # # # # # # # #                     message_placeholder.markdown(full_response + "▌")

# # # # # # # # # # # # # # # # #             message_placeholder.markdown(full_response)

# # # # # # # # # # # # # # # # #             st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # # # # # # # # # # # # #         except Exception as e:
# # # # # # # # # # # # # # # # #             st.error(f"An error occurred: {e}")




# # # # # # # # # # # # # # # # import os
# # # # # # # # # # # # # # # # import streamlit as st
# # # # # # # # # # # # # # # # from openai import AzureOpenAI
# # # # # # # # # # # # # # # # from dotenv import load_dotenv

# # # # # # # # # # # # # # # # # Load environment variables
# # # # # # # # # # # # # # # # load_dotenv()

# # # # # # # # # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # # # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # # # # # # # # # # Initialize the Azure OpenAI client
# # # # # # # # # # # # # # # # client = AzureOpenAI(
# # # # # # # # # # # # # # # #     api_key=azure_openai_api_key,   
# # # # # # # # # # # # # # # #     azure_endpoint=azure_endpoint,
# # # # # # # # # # # # # # # #     api_version="2024-04-01-preview",
# # # # # # # # # # # # # # # # )

# # # # # # # # # # # # # # # # st.title("My Own ChatGPT!🤖")

# # # # # # # # # # # # # # # # # Initialize session state for messages and model
# # # # # # # # # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # # # # # # # # #     st.session_state.messages = [
# # # # # # # # # # # # # # # #         {
# # # # # # # # # # # # # # # #             "role": "system",
# # # # # # # # # # # # # # # #             "content": "You are an AI assistant that helps people find information.",
# # # # # # # # # # # # # # # #         }
# # # # # # # # # # # # # # # #     ]

# # # # # # # # # # # # # # # # if "model" not in st.session_state:
# # # # # # # # # # # # # # # #     st.session_state.model = "gpt-4o"

# # # # # # # # # # # # # # # # # Display previous chat messages
# # # # # # # # # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # # # # # # # # User input
# # # # # # # # # # # # # # # # if user_prompt := st.chat_input("Your prompt"):
# # # # # # # # # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # # # # # # # # #     with st.chat_message("user"):
# # # # # # # # # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # # # # # # # # #     # Generate responses
# # # # # # # # # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # # # # # # # # #         full_response = ""

# # # # # # # # # # # # # # # #         try:
# # # # # # # # # # # # # # # #             stream = client.chat.completions.create(
# # # # # # # # # # # # # # # #                 model=st.session_state.model,
# # # # # # # # # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # # # # # # # # #                 stream=True,
# # # # # # # # # # # # # # # #                 max_tokens=4000,
# # # # # # # # # # # # # # # #                 temperature=0.2,
# # # # # # # # # # # # # # # #             )
# # # # # # # # # # # # # # # #             for chunk in stream:
# # # # # # # # # # # # # # # #                 token = chunk.choices[0].delta.get("content", "")
# # # # # # # # # # # # # # # #                 if token:
# # # # # # # # # # # # # # # #                     full_response += token
# # # # # # # # # # # # # # # #                     message_placeholder.markdown(full_response + "▌")
# # # # # # # # # # # # # # # #             message_placeholder.markdown(full_response)
# # # # # # # # # # # # # # # #         except Exception as e:
# # # # # # # # # # # # # # # #             st.error(f"An error occurred: {e}")
# # # # # # # # # # # # # # # #             full_response = f"An error occurred: {e}"

# # # # # # # # # # # # # # # #     st.session_state.messages.append({"role": "assistant", "content": full_response})


# # # # # # # # # # # # # # # import os
# # # # # # # # # # # # # # # import streamlit as st
# # # # # # # # # # # # # # # from openai import AzureOpenAI
# # # # # # # # # # # # # # # from dotenv import load_dotenv

# # # # # # # # # # # # # # # # Load environment variables
# # # # # # # # # # # # # # # load_dotenv()

# # # # # # # # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # # # # # # # # # Initialize the Azure OpenAI client
# # # # # # # # # # # # # # # client = AzureOpenAI(
# # # # # # # # # # # # # # #     api_key=azure_openai_api_key,
# # # # # # # # # # # # # # #     azure_endpoint=azure_endpoint,
# # # # # # # # # # # # # # #     api_version="2024-04-01-preview",
# # # # # # # # # # # # # # # )

# # # # # # # # # # # # # # # st.title("My Own ChatGPT!🤖")

# # # # # # # # # # # # # # # # Initialize session state for messages and model
# # # # # # # # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # # # # # # # #     st.session_state.messages = [
# # # # # # # # # # # # # # #         {
# # # # # # # # # # # # # # #             "role": "system",
# # # # # # # # # # # # # # #             "content": "You are an AI assistant that helps people find information.",
# # # # # # # # # # # # # # #         }
# # # # # # # # # # # # # # #     ]

# # # # # # # # # # # # # # # if "model" not in st.session_state:
# # # # # # # # # # # # # # #     st.session_state.model = "gpt-4o"

# # # # # # # # # # # # # # # # Display previous chat messages
# # # # # # # # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # # # # # # # User input
# # # # # # # # # # # # # # # if user_prompt := st.chat_input("Your prompt"):
# # # # # # # # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # # # # # # # #     with st.chat_message("user"):
# # # # # # # # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # # # # # # # #     # Generate responses
# # # # # # # # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # # # # # # # #         full_response = ""

# # # # # # # # # # # # # # #         try:
# # # # # # # # # # # # # # #             stream = client.chat.completions.create(
# # # # # # # # # # # # # # #                 model=st.session_state.model,
# # # # # # # # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # # # # # # # #                 stream=True,
# # # # # # # # # # # # # # #                 max_tokens=4000,
# # # # # # # # # # # # # # #                 temperature=0.2,
# # # # # # # # # # # # # # #             )
# # # # # # # # # # # # # # #             for chunk in stream:
# # # # # # # # # # # # # # #                 # Debugging: Print the chunk to inspect its content
# # # # # # # # # # # # # # #                 st.write(chunk)

# # # # # # # # # # # # # # #                 choices = chunk.get('choices', [])
# # # # # # # # # # # # # # #                 if choices:
# # # # # # # # # # # # # # #                     delta = choices[0].get('delta', {})
# # # # # # # # # # # # # # #                     token = delta.get('content', '')
# # # # # # # # # # # # # # #                     if token:
# # # # # # # # # # # # # # #                         full_response += token
# # # # # # # # # # # # # # #                         message_placeholder.markdown(full_response + "▌")
# # # # # # # # # # # # # # #             message_placeholder.markdown(full_response)
# # # # # # # # # # # # # # #         except Exception as e:
# # # # # # # # # # # # # # #             st.error(f"An error occurred: {e}")
# # # # # # # # # # # # # # #             full_response = f"An error occurred: {e}"

# # # # # # # # # # # # # # #     st.session_state.messages.append({"role": "assistant", "content": full_response})
# # # # # # # # # # # # # # import os
# # # # # # # # # # # # # # import streamlit as st
# # # # # # # # # # # # # # from openai import AzureOpenAI
# # # # # # # # # # # # # # from dotenv import load_dotenv

# # # # # # # # # # # # # # # Load environment variables
# # # # # # # # # # # # # # load_dotenv()

# # # # # # # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # # # # # # # # Initialize the Azure OpenAI client
# # # # # # # # # # # # # # client = AzureOpenAI(
# # # # # # # # # # # # # #     api_key=azure_openai_api_key,
# # # # # # # # # # # # # #     azure_endpoint=azure_endpoint,
# # # # # # # # # # # # # #     api_version="2024-04-01-preview",
# # # # # # # # # # # # # # )

# # # # # # # # # # # # # # st.title("SynoGPT!🤖")

# # # # # # # # # # # # # # # # Initialize session state for messages and model
# # # # # # # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # # # # # # #     st.session_state.messages = []
# # # # # # # # # # # # # #     #     {
# # # # # # # # # # # # # #     #         "role": "system",
# # # # # # # # # # # # # #     #         "content": "What do you want to query?",
# # # # # # # # # # # # # #     #     }
# # # # # # # # # # # # # #     # ]

# # # # # # # # # # # # # # if "model" not in st.session_state:
# # # # # # # # # # # # # #     st.session_state.model = "gpt-4o"

# # # # # # # # # # # # # # # Display previous chat messages
# # # # # # # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # # # # # # User input
# # # # # # # # # # # # # # if user_prompt := st.chat_input("Your prompt"):
# # # # # # # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # # # # # # #     with st.chat_message("user"):
# # # # # # # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # # # # # # #     # Generate responses
# # # # # # # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # # # # # # #         full_response = ""

# # # # # # # # # # # # # #         try:
# # # # # # # # # # # # # #             stream = client.chat.completions.create(
# # # # # # # # # # # # # #                 model=st.session_state.model,
# # # # # # # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # # # # # # #                 stream=True,
# # # # # # # # # # # # # #                 max_tokens=4000,
# # # # # # # # # # # # # #                 temperature=0.2,
# # # # # # # # # # # # # #             )
# # # # # # # # # # # # # #             for chunk in stream:
# # # # # # # # # # # # # #                 # Debugging: Print the chunk to inspect its content
# # # # # # # # # # # # # #                 # st.write(chunk)  # Uncomment this line if you want to see the chunk structure

# # # # # # # # # # # # # #                 # Access choices as an attribute
# # # # # # # # # # # # # #                 choices = getattr(chunk, 'choices', None)
# # # # # # # # # # # # # #                 if choices:
# # # # # # # # # # # # # #                     # Access the first choice
# # # # # # # # # # # # # #                     choice = choices[0]
# # # # # # # # # # # # # #                     # Access delta as an attribute
# # # # # # # # # # # # # #                     delta = getattr(choice, 'delta', None)
# # # # # # # # # # # # # #                     if delta:
# # # # # # # # # # # # # #                         # Get content from delta
# # # # # # # # # # # # # #                         token = getattr(delta, 'content', '')
# # # # # # # # # # # # # #                         if token:
# # # # # # # # # # # # # #                             full_response += token
# # # # # # # # # # # # # #                             message_placeholder.markdown(full_response + "▌")
# # # # # # # # # # # # # #             message_placeholder.markdown(full_response)
# # # # # # # # # # # # # #         except Exception as e:
# # # # # # # # # # # # # #             st.error(f"An error occurred: {e}")
# # # # # # # # # # # # # #             full_response = f"An error occurred: {e}"

# # # # # # # # # # # # # #     st.session_state.messages.append({"role": "assistant", "content": full_response})


# # # # # # # # # # # # # import os
# # # # # # # # # # # # # import json
# # # # # # # # # # # # # import datetime
# # # # # # # # # # # # # import streamlit as st
# # # # # # # # # # # # # from openai import AzureOpenAI
# # # # # # # # # # # # # from dotenv import load_dotenv

# # # # # # # # # # # # # # Load environment variables
# # # # # # # # # # # # # load_dotenv()

# # # # # # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # # # # # # # Initialize the Azure OpenAI client
# # # # # # # # # # # # # client = AzureOpenAI(
# # # # # # # # # # # # #     api_key=azure_openai_api_key,
# # # # # # # # # # # # #     azure_endpoint=azure_endpoint,
# # # # # # # # # # # # #     api_version="2024-04-01-preview",
# # # # # # # # # # # # # )

# # # # # # # # # # # # # st.title("SynoGPT!🤖")

# # # # # # # # # # # # # # Path to the conversations file
# # # # # # # # # # # # # CONVERSATIONS_FILE = "conversations.json"

# # # # # # # # # # # # # # Function to load conversations from file
# # # # # # # # # # # # # def load_conversations():
# # # # # # # # # # # # #     if os.path.exists(CONVERSATIONS_FILE):
# # # # # # # # # # # # #         with open(CONVERSATIONS_FILE, "r") as f:
# # # # # # # # # # # # #             return json.load(f)
# # # # # # # # # # # # #     else:
# # # # # # # # # # # # #         return []

# # # # # # # # # # # # # # Function to save a conversation
# # # # # # # # # # # # # def save_conversation(conversation):
# # # # # # # # # # # # #     conversations = load_conversations()
# # # # # # # # # # # # #     # Append the new conversation with timestamp
# # # # # # # # # # # # #     conversations.append({
# # # # # # # # # # # # #         "timestamp": datetime.datetime.now().isoformat(),
# # # # # # # # # # # # #         "messages": conversation
# # # # # # # # # # # # #     })
# # # # # # # # # # # # #     # Limit to the most recent 30 conversations
# # # # # # # # # # # # #     conversations = conversations[-30:]
# # # # # # # # # # # # #     with open(CONVERSATIONS_FILE, "w") as f:
# # # # # # # # # # # # #         json.dump(conversations, f, indent=4)

# # # # # # # # # # # # # # Sidebar to display conversations
# # # # # # # # # # # # # def display_sidebar():
# # # # # # # # # # # # #     st.sidebar.title("Conversations")

# # # # # # # # # # # # #     conversations = load_conversations()

# # # # # # # # # # # # #     # Categorize conversations
# # # # # # # # # # # # #     today = []
# # # # # # # # # # # # #     previous_7_days = []
# # # # # # # # # # # # #     previous_30_days = []

# # # # # # # # # # # # #     now = datetime.datetime.now()
# # # # # # # # # # # # #     for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # # # # # # # # # #         timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # # # # # # # # # #         delta = now - timestamp
# # # # # # # # # # # # #         if delta.days == 0:
# # # # # # # # # # # # #             today.append((idx, convo))
# # # # # # # # # # # # #         elif delta.days <= 7:
# # # # # # # # # # # # #             previous_7_days.append((idx, convo))
# # # # # # # # # # # # #         elif delta.days <= 30:
# # # # # # # # # # # # #             previous_30_days.append((idx, convo))

# # # # # # # # # # # # #     # Display categories
# # # # # # # # # # # # #     if today:
# # # # # # # # # # # # #         st.sidebar.subheader("Today")
# # # # # # # # # # # # #         for idx, convo in today:
# # # # # # # # # # # # #             if st.sidebar.button(f"Conversation {idx + 1}", key=f"today_{idx}"):
# # # # # # # # # # # # #                 st.session_state.messages = convo["messages"]

# # # # # # # # # # # # #     if previous_7_days:
# # # # # # # # # # # # #         st.sidebar.subheader("Previous 7 Days")
# # # # # # # # # # # # #         for idx, convo in previous_7_days:
# # # # # # # # # # # # #             if st.sidebar.button(f"Conversation {idx + 1}", key=f"week_{idx}"):
# # # # # # # # # # # # #                 st.session_state.messages = convo["messages"]

# # # # # # # # # # # # #     if previous_30_days:
# # # # # # # # # # # # #         st.sidebar.subheader("Previous 30 Days")
# # # # # # # # # # # # #         for idx, convo in previous_30_days:
# # # # # # # # # # # # #             if st.sidebar.button(f"Conversation {idx + 1}", key=f"month_{idx}"):
# # # # # # # # # # # # #                 st.session_state.messages = convo["messages"]

# # # # # # # # # # # # # # Call the sidebar function
# # # # # # # # # # # # # display_sidebar()

# # # # # # # # # # # # # # Initialize session state for messages and model
# # # # # # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # # # # # #     st.session_state.messages = []

# # # # # # # # # # # # # if "model" not in st.session_state:
# # # # # # # # # # # # #     st.session_state.model = "gpt-4o"

# # # # # # # # # # # # # # Display previous chat messages
# # # # # # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # # # # # User input
# # # # # # # # # # # # # if user_prompt := st.chat_input("Your prompt"):
# # # # # # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # # # # # #     with st.chat_message("user"):
# # # # # # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # # # # # #     # Generate responses
# # # # # # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # # # # # #         full_response = ""

# # # # # # # # # # # # #         try:
# # # # # # # # # # # # #             stream = client.chat.completions.create(
# # # # # # # # # # # # #                 model=st.session_state.model,
# # # # # # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # # # # # #                 stream=True,
# # # # # # # # # # # # #                 max_tokens=4000,
# # # # # # # # # # # # #                 temperature=0.2,
# # # # # # # # # # # # #             )
# # # # # # # # # # # # #             for chunk in stream:
# # # # # # # # # # # # #                 # Access choices as an attribute
# # # # # # # # # # # # #                 choices = getattr(chunk, 'choices', None)
# # # # # # # # # # # # #                 if choices:
# # # # # # # # # # # # #                     # Access the first choice
# # # # # # # # # # # # #                     choice = choices[0]
# # # # # # # # # # # # #                     # Access delta as an attribute
# # # # # # # # # # # # #                     delta = getattr(choice, 'delta', None)
# # # # # # # # # # # # #                     if delta:
# # # # # # # # # # # # #                         # Get content from delta
# # # # # # # # # # # # #                         token = getattr(delta, 'content', '')
# # # # # # # # # # # # #                         if token:
# # # # # # # # # # # # #                             full_response += token
# # # # # # # # # # # # #                             message_placeholder.markdown(full_response + "▌")
# # # # # # # # # # # # #             message_placeholder.markdown(full_response)
# # # # # # # # # # # # #         except Exception as e:
# # # # # # # # # # # # #             st.error(f"An error occurred: {e}")
# # # # # # # # # # # # #             full_response = f"An error occurred: {e}"

# # # # # # # # # # # # #     st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # # # # # # # # #     # Save the conversation after each assistant response
# # # # # # # # # # # # #     save_conversation(st.session_state.messages)



# # # # # # # # # # # # import os
# # # # # # # # # # # # import json
# # # # # # # # # # # # import datetime
# # # # # # # # # # # # import streamlit as st
# # # # # # # # # # # # from openai import AzureOpenAI
# # # # # # # # # # # # from dotenv import load_dotenv

# # # # # # # # # # # # # Load environment variables
# # # # # # # # # # # # load_dotenv()

# # # # # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # # # # # st.set_page_config(page_title="SynoGPT", page_icon="🤖", layout="wide", initial_sidebar_state="auto")

# # # # # # # # # # # # # Initialize the Azure OpenAI client
# # # # # # # # # # # # client = AzureOpenAI(
# # # # # # # # # # # #     api_key=azure_openai_api_key,
# # # # # # # # # # # #     azure_endpoint=azure_endpoint,
# # # # # # # # # # # #     api_version="2024-04-01-preview",
# # # # # # # # # # # # )

# # # # # # # # # # # # st.title("SynoGPT!🤖")

# # # # # # # # # # # # # colored_header(label="SynoGPT! 🤖", description="\n", color_name="violet-70")


# # # # # # # # # # # # # Path to the conversations file
# # # # # # # # # # # # CONVERSATIONS_FILE = "conversations.json"

# # # # # # # # # # # # # Function to load conversations from file
# # # # # # # # # # # # def load_conversations():
# # # # # # # # # # # #     if os.path.exists(CONVERSATIONS_FILE):
# # # # # # # # # # # #         with open(CONVERSATIONS_FILE, "r") as f:
# # # # # # # # # # # #             return json.load(f)
# # # # # # # # # # # #     else:
# # # # # # # # # # # #         return []

# # # # # # # # # # # # # Function to save a conversation
# # # # # # # # # # # # def save_conversation(conversation):
# # # # # # # # # # # #     conversations = load_conversations()
# # # # # # # # # # # #     # Append the new conversation with timestamp
# # # # # # # # # # # #     conversations.append({
# # # # # # # # # # # #         "timestamp": datetime.datetime.now().isoformat(),
# # # # # # # # # # # #         "messages": conversation
# # # # # # # # # # # #     })
# # # # # # # # # # # #     # Limit to the most recent 30 conversations
# # # # # # # # # # # #     conversations = conversations[-30:]
# # # # # # # # # # # #     with open(CONVERSATIONS_FILE, "w") as f:
# # # # # # # # # # # #         json.dump(conversations, f, indent=4)

# # # # # # # # # # # # # Function to generate a title from the first user message
# # # # # # # # # # # # def get_conversation_title(conversation):
# # # # # # # # # # # #     for msg in conversation["messages"]:
# # # # # # # # # # # #         if msg["role"] == "user":
# # # # # # # # # # # #             title = msg["content"].strip()
# # # # # # # # # # # #             # Truncate title if it's too long
# # # # # # # # # # # #             return title[:30] + "..." if len(title) > 30 else title
# # # # # # # # # # # #     return "Untitled Conversation"

# # # # # # # # # # # # # Sidebar to display conversations
# # # # # # # # # # # # def display_sidebar():
# # # # # # # # # # # #     st.sidebar.title("Conversations")

# # # # # # # # # # # #     # Add "New Chat" button at the top
# # # # # # # # # # # #     if st.sidebar.button("New Chat"):
# # # # # # # # # # # #         st.session_state.messages = []
# # # # # # # # # # # #         st.rerun()

# # # # # # # # # # # #     conversations = load_conversations()

# # # # # # # # # # # #     # Categorize conversations
# # # # # # # # # # # #     today = []
# # # # # # # # # # # #     previous_7_days = []
# # # # # # # # # # # #     previous_30_days = []

# # # # # # # # # # # #     now = datetime.datetime.now()
# # # # # # # # # # # #     for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # # # # # # # # #         timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # # # # # # # # #         delta = now - timestamp
# # # # # # # # # # # #         if delta.days == 0:
# # # # # # # # # # # #             today.append((idx, convo))
# # # # # # # # # # # #         elif delta.days <= 7:
# # # # # # # # # # # #             previous_7_days.append((idx, convo))
# # # # # # # # # # # #         elif delta.days <= 30:
# # # # # # # # # # # #             previous_30_days.append((idx, convo))

# # # # # # # # # # # #     # Display categories
# # # # # # # # # # # #     if today:
# # # # # # # # # # # #         st.sidebar.subheader("Today")
# # # # # # # # # # # #         for idx, convo in today:
# # # # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # # # #             if st.sidebar.button(title, key=f"today_{idx}"):
# # # # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # # # #                 st.rerun()

# # # # # # # # # # # #     if previous_7_days:
# # # # # # # # # # # #         st.sidebar.subheader("Previous 7 Days")
# # # # # # # # # # # #         for idx, convo in previous_7_days:
# # # # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # # # #             if st.sidebar.button(title, key=f"week_{idx}"):
# # # # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # # # #                 st.rerun()

# # # # # # # # # # # #     if previous_30_days:
# # # # # # # # # # # #         st.sidebar.subheader("Previous 30 Days")
# # # # # # # # # # # #         for idx, convo in previous_30_days:
# # # # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # # # #             if st.sidebar.button(title, key=f"month_{idx}"):
# # # # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # # # #                 st.rerun()

# # # # # # # # # # # # # Call the sidebar function
# # # # # # # # # # # # display_sidebar()

# # # # # # # # # # # # # Initialize session state for messages and model
# # # # # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # # # # #     st.session_state.messages = []

# # # # # # # # # # # # if "model" not in st.session_state:
# # # # # # # # # # # #     st.session_state.model = "gpt-4o"

# # # # # # # # # # # # # Display previous chat messages
# # # # # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # # # # User input
# # # # # # # # # # # # if user_prompt := st.chat_input("Type here to Chat..."):
# # # # # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # # # # #     with st.chat_message("user"):
# # # # # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # # # # #     # Generate responses
# # # # # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # # # # #         full_response = ""

# # # # # # # # # # # #         try:
# # # # # # # # # # # #             stream = client.chat.completions.create(
# # # # # # # # # # # #                 model=st.session_state.model,
# # # # # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # # # # #                 stream=True,
# # # # # # # # # # # #                 max_tokens=4000,
# # # # # # # # # # # #                 temperature=0.2,
# # # # # # # # # # # #             )
# # # # # # # # # # # #             for chunk in stream:
# # # # # # # # # # # #                 # Access choices as an attribute
# # # # # # # # # # # #                 choices = getattr(chunk, 'choices', None)
# # # # # # # # # # # #                 if choices:
# # # # # # # # # # # #                     # Access the first choice
# # # # # # # # # # # #                     choice = choices[0]
# # # # # # # # # # # #                     # Access delta as an attribute
# # # # # # # # # # # #                     delta = getattr(choice, 'delta', None)
# # # # # # # # # # # #                     if delta:
# # # # # # # # # # # #                         # Get content from delta
# # # # # # # # # # # #                         token = getattr(delta, 'content', '')
# # # # # # # # # # # #                         if token:
# # # # # # # # # # # #                             full_response += token
# # # # # # # # # # # #                             message_placeholder.markdown(full_response + "▌")
# # # # # # # # # # # #             message_placeholder.markdown(full_response)
# # # # # # # # # # # #         except Exception as e:
# # # # # # # # # # # #             st.error(f"An error occurred: {e}")
# # # # # # # # # # # #             full_response = f"An error occurred: {e}"

# # # # # # # # # # # #     st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # # # # # # # #     # Save the conversation after each assistant response
# # # # # # # # # # # #     save_conversation(st.session_state.messages)



# # # # # # # # # # # import os
# # # # # # # # # # # import json
# # # # # # # # # # # import datetime
# # # # # # # # # # # import streamlit as st
# # # # # # # # # # # from openai import AzureOpenAI
# # # # # # # # # # # from dotenv import load_dotenv

# # # # # # # # # # # # Load environment variables
# # # # # # # # # # # load_dotenv()

# # # # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # # # # st.set_page_config(
# # # # # # # # # # #     page_title="SynoGPT",
# # # # # # # # # # #     page_icon="🤖",
# # # # # # # # # # #     layout="wide",
# # # # # # # # # # #     initial_sidebar_state="auto"
# # # # # # # # # # # )

# # # # # # # # # # # # Initialize the Azure OpenAI client
# # # # # # # # # # # client = AzureOpenAI(
# # # # # # # # # # #     api_key=azure_openai_api_key,
# # # # # # # # # # #     azure_endpoint=azure_endpoint,
# # # # # # # # # # #     api_version="2024-04-01-preview",
# # # # # # # # # # # )

# # # # # # # # # # # st.title("SynoGPT! 🤖")

# # # # # # # # # # # with st.sidebar:
# # # # # # # # # # #     st.image(r"./synoptek.png", width=275)

# # # # # # # # # # # # Path to the conversations file
# # # # # # # # # # # CONVERSATIONS_FILE = "conversations.json"

# # # # # # # # # # # # Function to load conversations from file
# # # # # # # # # # # def load_conversations():
# # # # # # # # # # #     if os.path.exists(CONVERSATIONS_FILE):
# # # # # # # # # # #         with open(CONVERSATIONS_FILE, "r") as f:
# # # # # # # # # # #             return json.load(f)
# # # # # # # # # # #     else:
# # # # # # # # # # #         return []

# # # # # # # # # # # # Function to save a conversation
# # # # # # # # # # # def save_conversation(conversation):
# # # # # # # # # # #     conversations = load_conversations()
# # # # # # # # # # #     # Append the new conversation with timestamp
# # # # # # # # # # #     conversations.append({
# # # # # # # # # # #         "timestamp": datetime.datetime.now().isoformat(),
# # # # # # # # # # #         "messages": conversation
# # # # # # # # # # #     })
# # # # # # # # # # #     # Limit to the most recent 30 conversations
# # # # # # # # # # #     conversations = conversations[-30:]
# # # # # # # # # # #     with open(CONVERSATIONS_FILE, "w") as f:
# # # # # # # # # # #         json.dump(conversations, f, indent=4)

# # # # # # # # # # # # Function to generate a title from the first user message
# # # # # # # # # # # def get_conversation_title(conversation):
# # # # # # # # # # #     for msg in conversation["messages"]:
# # # # # # # # # # #         if msg["role"] == "user":
# # # # # # # # # # #             title = msg["content"].strip()
# # # # # # # # # # #             # Truncate title if it's too long
# # # # # # # # # # #             return title[:28] + "..." if len(title) > 28 else title
# # # # # # # # # # #     return "Untitled Conversation"

# # # # # # # # # # # # Sidebar to display conversations
# # # # # # # # # # # def display_sidebar():
# # # # # # # # # # #     st.sidebar.title("Conversations")

# # # # # # # # # # #     # Add "New Chat" button at the top
# # # # # # # # # # #     if st.sidebar.button("New Chat"):
# # # # # # # # # # #         st.session_state.messages = []
# # # # # # # # # # #         st.rerun()

# # # # # # # # # # #     conversations = load_conversations()

# # # # # # # # # # #     # Categorize conversations
# # # # # # # # # # #     today = []
# # # # # # # # # # #     yesterday = []
# # # # # # # # # # #     previous_7_days = []
# # # # # # # # # # #     previous_30_days = []

# # # # # # # # # # #     now = datetime.datetime.now()
# # # # # # # # # # #     for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # # # # # # # #         timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # # # # # # # #         delta = now - timestamp
# # # # # # # # # # #         if delta.days == 0:
# # # # # # # # # # #             today.append((idx, convo))
# # # # # # # # # # #         elif delta.days == 1:
# # # # # # # # # # #             yesterday.append((idx, convo))
# # # # # # # # # # #         elif delta.days <= 7:
# # # # # # # # # # #             previous_7_days.append((idx, convo))
# # # # # # # # # # #         elif delta.days <= 30:
# # # # # # # # # # #             previous_30_days.append((idx, convo))

# # # # # # # # # # #     # Display categories
# # # # # # # # # # #     if today:
# # # # # # # # # # #         st.sidebar.subheader("Today")
# # # # # # # # # # #         for idx, convo in today:
# # # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # # #             if st.sidebar.button(title, key=f"today_{idx}"):
# # # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # # #                 st.rerun()

# # # # # # # # # # #     if yesterday:
# # # # # # # # # # #         st.sidebar.subheader("Yesterday")
# # # # # # # # # # #         for idx, convo in yesterday:
# # # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # # #             if st.sidebar.button(title, key=f"yesterday_{idx}"):
# # # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # # #                 st.rerun()

# # # # # # # # # # #     if previous_7_days:
# # # # # # # # # # #         st.sidebar.subheader("Previous 7 Days")
# # # # # # # # # # #         for idx, convo in previous_7_days:
# # # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # # #             if st.sidebar.button(title, key=f"week_{idx}"):
# # # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # # #                 st.rerun()

# # # # # # # # # # #     if previous_30_days:
# # # # # # # # # # #         st.sidebar.subheader("Previous 30 Days")
# # # # # # # # # # #         for idx, convo in previous_30_days:
# # # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # # #             if st.sidebar.button(title, key=f"month_{idx}"):
# # # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # # #                 st.rerun()

# # # # # # # # # # # # Call the sidebar function
# # # # # # # # # # # display_sidebar()

# # # # # # # # # # # # Initialize session state for messages and model
# # # # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # # # #     st.session_state.messages = []

# # # # # # # # # # # if "model" not in st.session_state:
# # # # # # # # # # #     st.session_state.model = "gpt-4o"

# # # # # # # # # # # # Display previous chat messages
# # # # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # # # User input
# # # # # # # # # # # if user_prompt := st.chat_input("Type here to Chat..."):
# # # # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # # # #     with st.chat_message("user"):
# # # # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # # # #     # Generate responses
# # # # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # # # #         full_response = ""

# # # # # # # # # # #         try:
# # # # # # # # # # #             stream = client.chat.completions.create(
# # # # # # # # # # #                 model=st.session_state.model,
# # # # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # # # #                 stream=True,
# # # # # # # # # # #                 max_tokens=4000,
# # # # # # # # # # #                 temperature=0.2,
# # # # # # # # # # #             )
# # # # # # # # # # #             for chunk in stream:
# # # # # # # # # # #                 # Access choices as an attribute
# # # # # # # # # # #                 choices = getattr(chunk, 'choices', None)
# # # # # # # # # # #                 if choices:
# # # # # # # # # # #                     # Access the first choice
# # # # # # # # # # #                     choice = choices[0]
# # # # # # # # # # #                     # Access delta as an attribute
# # # # # # # # # # #                     delta = getattr(choice, 'delta', None)
# # # # # # # # # # #                     if delta:
# # # # # # # # # # #                         # Get content from delta
# # # # # # # # # # #                         token = getattr(delta, 'content', '')
# # # # # # # # # # #                         if token:
# # # # # # # # # # #                             full_response += token
# # # # # # # # # # #                             message_placeholder.markdown(full_response + "▌")
# # # # # # # # # # #             message_placeholder.markdown(full_response)
# # # # # # # # # # #         except Exception as e:
# # # # # # # # # # #             st.error(f"An error occurred: {e}")
# # # # # # # # # # #             full_response = f"An error occurred: {e}"

# # # # # # # # # # #     st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # # # # # # #     # Save the conversation after each assistant response
# # # # # # # # # # #     save_conversation(st.session_state.messages)



# # # # # # # # # # import os
# # # # # # # # # # import json
# # # # # # # # # # import datetime
# # # # # # # # # # import logging  # For logging
# # # # # # # # # # import streamlit as st
# # # # # # # # # # from openai import AzureOpenAI
# # # # # # # # # # from dotenv import load_dotenv

# # # # # # # # # # # Load environment variables
# # # # # # # # # # load_dotenv()

# # # # # # # # # # # Set up logging
# # # # # # # # # # logging.basicConfig(
# # # # # # # # # #     filename='app.log',
# # # # # # # # # #     level=logging.ERROR,
# # # # # # # # # #     format='%(asctime)s %(levelname)s %(message)s'
# # # # # # # # # # )

# # # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # # # st.set_page_config(
# # # # # # # # # #     page_title="SynoGPT",
# # # # # # # # # #     page_icon="🤖",
# # # # # # # # # #     layout="wide",
# # # # # # # # # #     initial_sidebar_state="auto"
# # # # # # # # # # )

# # # # # # # # # # # Initialize the Azure OpenAI client with error handling
# # # # # # # # # # try:
# # # # # # # # # #     client = AzureOpenAI(
# # # # # # # # # #         api_key=azure_openai_api_key,
# # # # # # # # # #         azure_endpoint=azure_endpoint,
# # # # # # # # # #         api_version="2024-04-01-preview",
# # # # # # # # # #     )
# # # # # # # # # # except Exception as e:
# # # # # # # # # #     st.error("Failed to initialize Azure OpenAI client.")
# # # # # # # # # #     logging.error(f"OpenAI Client Initialization Error: {e}")
# # # # # # # # # #     st.stop()

# # # # # # # # # # st.title("SynoGPT! 🤖")

# # # # # # # # # # with st.sidebar:
# # # # # # # # # #     st.image(r"./synoptek.png", width=275)

# # # # # # # # # # # Path to the conversations file
# # # # # # # # # # CONVERSATIONS_FILE = "conversations.json"

# # # # # # # # # # # Function to load conversations from file with error handling
# # # # # # # # # # def load_conversations():
# # # # # # # # # #     try:
# # # # # # # # # #         if os.path.exists(CONVERSATIONS_FILE):
# # # # # # # # # #             with open(CONVERSATIONS_FILE, "r") as f:
# # # # # # # # # #                 return json.load(f)
# # # # # # # # # #         else:
# # # # # # # # # #             return []
# # # # # # # # # #     except Exception as e:
# # # # # # # # # #         st.error("Failed to load conversations.")
# # # # # # # # # #         logging.error(f"Load Conversations Error: {e}")
# # # # # # # # # #         return []

# # # # # # # # # # # Function to save a conversation with error handling
# # # # # # # # # # def save_conversation(conversation):
# # # # # # # # # #     try:
# # # # # # # # # #         conversations = load_conversations()
# # # # # # # # # #         # Append the new conversation with timestamp
# # # # # # # # # #         conversations.append({
# # # # # # # # # #             "timestamp": datetime.datetime.now().isoformat(),
# # # # # # # # # #             "messages": conversation
# # # # # # # # # #         })
# # # # # # # # # #         # Limit to the most recent 30 conversations
# # # # # # # # # #         conversations = conversations[-30:]
# # # # # # # # # #         with open(CONVERSATIONS_FILE, "w") as f:
# # # # # # # # # #             json.dump(conversations, f, indent=4)
# # # # # # # # # #     except Exception as e:
# # # # # # # # # #         st.error("Failed to save conversation.")
# # # # # # # # # #         logging.error(f"Save Conversation Error: {e}")

# # # # # # # # # # # Function to generate a title from the first user message
# # # # # # # # # # def get_conversation_title(conversation):
# # # # # # # # # #     for msg in conversation["messages"]:
# # # # # # # # # #         if msg["role"] == "user":
# # # # # # # # # #             title = msg["content"].strip()
# # # # # # # # # #             # Truncate title if it's too long
# # # # # # # # # #             return title[:28] + "..." if len(title) > 28 else title
# # # # # # # # # #     return "Untitled Conversation"

# # # # # # # # # # # Sidebar to display conversations
# # # # # # # # # # def display_sidebar():
# # # # # # # # # #     st.sidebar.title("Conversations")

# # # # # # # # # #     # Add "New Chat" button at the top
# # # # # # # # # #     if st.sidebar.button("New Chat"):
# # # # # # # # # #         st.session_state.messages = []
# # # # # # # # # #         st.rerun()

# # # # # # # # # #     conversations = load_conversations()

# # # # # # # # # #     # Categorize conversations
# # # # # # # # # #     today = []
# # # # # # # # # #     yesterday = []
# # # # # # # # # #     previous_7_days = []
# # # # # # # # # #     previous_30_days = []

# # # # # # # # # #     now = datetime.datetime.now()
# # # # # # # # # #     for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # # # # # # #         try:
# # # # # # # # # #             timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # # # # # # #             delta = now - timestamp
# # # # # # # # # #             if delta.days == 0:
# # # # # # # # # #                 today.append((idx, convo))
# # # # # # # # # #             elif delta.days == 1:
# # # # # # # # # #                 yesterday.append((idx, convo))
# # # # # # # # # #             elif delta.days <= 7:
# # # # # # # # # #                 previous_7_days.append((idx, convo))
# # # # # # # # # #             elif delta.days <= 30:
# # # # # # # # # #                 previous_30_days.append((idx, convo))
# # # # # # # # # #         except Exception as e:
# # # # # # # # # #             logging.error(f"Error processing conversation timestamp: {e}")

# # # # # # # # # #     # Display categories
# # # # # # # # # #     if today:
# # # # # # # # # #         st.sidebar.subheader("Today")
# # # # # # # # # #         for idx, convo in today:
# # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # #             if st.sidebar.button(title, key=f"today_{idx}"):
# # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # #                 st.rerun()

# # # # # # # # # #     if yesterday:
# # # # # # # # # #         st.sidebar.subheader("Yesterday")
# # # # # # # # # #         for idx, convo in yesterday:
# # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # #             if st.sidebar.button(title, key=f"yesterday_{idx}"):
# # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # #                 st.rerun()

# # # # # # # # # #     if previous_7_days:
# # # # # # # # # #         st.sidebar.subheader("Previous 7 Days")
# # # # # # # # # #         for idx, convo in previous_7_days:
# # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # #             if st.sidebar.button(title, key=f"week_{idx}"):
# # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # #                 st.rerun()

# # # # # # # # # #     if previous_30_days:
# # # # # # # # # #         st.sidebar.subheader("Previous 30 Days")
# # # # # # # # # #         for idx, convo in previous_30_days:
# # # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # # #             if st.sidebar.button(title, key=f"month_{idx}"):
# # # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # # #                 st.rerun()

# # # # # # # # # # # Call the sidebar function
# # # # # # # # # # display_sidebar()

# # # # # # # # # # # Initialize session state for messages and model
# # # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # # #     st.session_state.messages = []

# # # # # # # # # # if "model" not in st.session_state:
# # # # # # # # # #     st.session_state.model = "gpt-4o"

# # # # # # # # # # # Display previous chat messages
# # # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # # User input
# # # # # # # # # # if user_prompt := st.chat_input("Type here to Chat..."):
# # # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # # #     with st.chat_message("user"):
# # # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # # #     # Generate responses with error handling
# # # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # # #         full_response = ""

# # # # # # # # # #         try:
# # # # # # # # # #             stream = client.chat.completions.create(
# # # # # # # # # #                 model=st.session_state.model,
# # # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # # #                 stream=True,
# # # # # # # # # #                 max_tokens=4000,
# # # # # # # # # #                 temperature=0.2,
# # # # # # # # # #             )
# # # # # # # # # #             for chunk in stream:
# # # # # # # # # #                 # Access choices as an attribute
# # # # # # # # # #                 choices = getattr(chunk, 'choices', None)
# # # # # # # # # #                 if choices:
# # # # # # # # # #                     # Access the first choice
# # # # # # # # # #                     choice = choices[0]
# # # # # # # # # #                     # Access delta as an attribute
# # # # # # # # # #                     delta = getattr(choice, 'delta', None)
# # # # # # # # # #                     if delta:
# # # # # # # # # #                         # Get content from delta
# # # # # # # # # #                         token = getattr(delta, 'content', '')
# # # # # # # # # #                         if token:
# # # # # # # # # #                             full_response += token
# # # # # # # # # #                             message_placeholder.markdown(full_response + "▌")
# # # # # # # # # #             message_placeholder.markdown(full_response)
# # # # # # # # # #         except Exception as e:
# # # # # # # # # #             st.error("An error occurred while generating the response.")
# # # # # # # # # #             logging.error(f"API Error: {e}")
# # # # # # # # # #             full_response = "I'm sorry, but I'm unable to process your request at the moment."

# # # # # # # # # #     st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # # # # # #     # Save the conversation after each assistant response
# # # # # # # # # #     save_conversation(st.session_state.messages)


# # # # # # # # # import os
# # # # # # # # # import json
# # # # # # # # # import datetime
# # # # # # # # # import logging  # For logging
# # # # # # # # # import streamlit as st
# # # # # # # # # from openai import AzureOpenAI
# # # # # # # # # from dotenv import load_dotenv

# # # # # # # # # # Load environment variables
# # # # # # # # # load_dotenv()

# # # # # # # # # # Set up logging to display on the command line
# # # # # # # # # logging.basicConfig(
# # # # # # # # #     level=logging.ERROR,
# # # # # # # # #     format='%(asctime)s %(levelname)s %(message)s'
# # # # # # # # # )

# # # # # # # # # # Azure OpenAI configuration
# # # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # # st.set_page_config(
# # # # # # # # #     page_title="Synoptek-GPT",
# # # # # # # # #     page_icon="🤖",
# # # # # # # # #     layout="wide",
# # # # # # # # #     initial_sidebar_state="auto"
# # # # # # # # # )

# # # # # # # # # # Initialize the Azure OpenAI client with error handling
# # # # # # # # # try:
# # # # # # # # #     client = AzureOpenAI(
# # # # # # # # #         api_key=azure_openai_api_key,
# # # # # # # # #         azure_endpoint=azure_endpoint,
# # # # # # # # #         api_version="2024-04-01-preview",
# # # # # # # # #     )
# # # # # # # # # except Exception as e:
# # # # # # # # #     st.error("Failed to initialize Azure OpenAI client.")
# # # # # # # # #     logging.error(f"OpenAI Client Initialization Error: {e}")
# # # # # # # # #     st.stop()

# # # # # # # # # st.title("SynoGPT! 🤖")

# # # # # # # # # with st.sidebar:
# # # # # # # # #     st.image(r"./synoptek.png", width=275)

# # # # # # # # # # Path to the conversations file
# # # # # # # # # CONVERSATIONS_FILE = "conversations.json"

# # # # # # # # # # Function to load conversations from file with error handling
# # # # # # # # # def load_conversations():
# # # # # # # # #     try:
# # # # # # # # #         if os.path.exists(CONVERSATIONS_FILE):
# # # # # # # # #             with open(CONVERSATIONS_FILE, "r") as f:
# # # # # # # # #                 return json.load(f)
# # # # # # # # #         else:
# # # # # # # # #             return []
# # # # # # # # #     except Exception as e:
# # # # # # # # #         st.error("Failed to load conversations.")
# # # # # # # # #         logging.error(f"Load Conversations Error: {e}")
# # # # # # # # #         return []

# # # # # # # # # # Function to save a conversation with error handling
# # # # # # # # # def save_conversation(conversation):
# # # # # # # # #     try:
# # # # # # # # #         conversations = load_conversations()
# # # # # # # # #         # Append the new conversation with timestamp
# # # # # # # # #         conversations.append({
# # # # # # # # #             "timestamp": datetime.datetime.now().isoformat(),
# # # # # # # # #             "messages": conversation
# # # # # # # # #         })
# # # # # # # # #         # Limit to the most recent 30 conversations
# # # # # # # # #         conversations = conversations[-30:]
# # # # # # # # #         with open(CONVERSATIONS_FILE, "w") as f:
# # # # # # # # #             json.dump(conversations, f, indent=4)
# # # # # # # # #     except Exception as e:
# # # # # # # # #         st.error("Failed to save conversation.")
# # # # # # # # #         logging.error(f"Save Conversation Error: {e}")

# # # # # # # # # # Function to generate a title from the first user message
# # # # # # # # # def get_conversation_title(conversation):
# # # # # # # # #     for msg in conversation["messages"]:
# # # # # # # # #         if msg["role"] == "user":
# # # # # # # # #             title = msg["content"].strip()
# # # # # # # # #             # Truncate title if it's too long
# # # # # # # # #             return title[:28] + "..." if len(title) > 28 else title
# # # # # # # # #     return "Untitled Conversation"

# # # # # # # # # # Sidebar to display conversations
# # # # # # # # # def display_sidebar():
# # # # # # # # #     st.sidebar.title("Conversations")

# # # # # # # # #     # Add "New Chat" button at the top
# # # # # # # # #     if st.sidebar.button("New Chat"):
# # # # # # # # #         st.session_state.messages = []
# # # # # # # # #         st.rerun()

# # # # # # # # #     conversations = load_conversations()

# # # # # # # # #     # Categorize conversations
# # # # # # # # #     today = []
# # # # # # # # #     yesterday = []
# # # # # # # # #     previous_7_days = []
# # # # # # # # #     previous_30_days = []

# # # # # # # # #     now = datetime.datetime.now()
# # # # # # # # #     for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # # # # # #         try:
# # # # # # # # #             timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # # # # # #             delta = now - timestamp
# # # # # # # # #             if delta.days == 0:
# # # # # # # # #                 today.append((idx, convo))
# # # # # # # # #             elif delta.days == 1:
# # # # # # # # #                 yesterday.append((idx, convo))
# # # # # # # # #             elif delta.days <= 7:
# # # # # # # # #                 previous_7_days.append((idx, convo))
# # # # # # # # #             elif delta.days <= 30:
# # # # # # # # #                 previous_30_days.append((idx, convo))
# # # # # # # # #         except Exception as e:
# # # # # # # # #             logging.error(f"Error processing conversation timestamp: {e}")

# # # # # # # # #     # Display categories
# # # # # # # # #     if today:
# # # # # # # # #         st.sidebar.subheader("Today")
# # # # # # # # #         for idx, convo in today:
# # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # #             if st.sidebar.button(title, key=f"today_{idx}"):
# # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # #                 st.rerun()

# # # # # # # # #     if yesterday:
# # # # # # # # #         st.sidebar.subheader("Yesterday")
# # # # # # # # #         for idx, convo in yesterday:
# # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # #             if st.sidebar.button(title, key=f"yesterday_{idx}"):
# # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # #                 st.rerun()

# # # # # # # # #     if previous_7_days:
# # # # # # # # #         st.sidebar.subheader("Previous 7 Days")
# # # # # # # # #         for idx, convo in previous_7_days:
# # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # #             if st.sidebar.button(title, key=f"week_{idx}"):
# # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # #                 st.rerun()

# # # # # # # # #     if previous_30_days:
# # # # # # # # #         st.sidebar.subheader("Previous 30 Days")
# # # # # # # # #         for idx, convo in previous_30_days:
# # # # # # # # #             title = get_conversation_title(convo)
# # # # # # # # #             if st.sidebar.button(title, key=f"month_{idx}"):
# # # # # # # # #                 st.session_state.messages = convo["messages"]
# # # # # # # # #                 st.rerun()

# # # # # # # # # # Call the sidebar function
# # # # # # # # # display_sidebar()

# # # # # # # # # # Initialize session state for messages and model
# # # # # # # # # if "messages" not in st.session_state:
# # # # # # # # #     st.session_state.messages = []

# # # # # # # # # if "model" not in st.session_state:
# # # # # # # # #     st.session_state.model = "gpt-4o"

# # # # # # # # # # Display previous chat messages
# # # # # # # # # for message in st.session_state["messages"]:
# # # # # # # # #     with st.chat_message(message["role"]):
# # # # # # # # #         st.markdown(message["content"])

# # # # # # # # # # User input
# # # # # # # # # if user_prompt := st.chat_input("Type here to Chat..."):
# # # # # # # # #     st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # # #     with st.chat_message("user"):
# # # # # # # # #         st.markdown(user_prompt)

# # # # # # # # #     # Generate responses with error handling
# # # # # # # # #     with st.chat_message("assistant"):
# # # # # # # # #         message_placeholder = st.empty()
# # # # # # # # #         full_response = ""

# # # # # # # # #         try:
# # # # # # # # #             stream = client.chat.completions.create(
# # # # # # # # #                 model=st.session_state.model,
# # # # # # # # #                 messages=st.session_state.messages,
# # # # # # # # #                 stream=True,
# # # # # # # # #                 max_tokens=4000,
# # # # # # # # #                 temperature=0.2,
# # # # # # # # #             )
# # # # # # # # #             for chunk in stream:
# # # # # # # # #                 # Access choices as an attribute
# # # # # # # # #                 choices = getattr(chunk, 'choices', None)
# # # # # # # # #                 if choices:
# # # # # # # # #                     # Access the first choice
# # # # # # # # #                     choice = choices[0]
# # # # # # # # #                     # Access delta as an attribute
# # # # # # # # #                     delta = getattr(choice, 'delta', None)
# # # # # # # # #                     if delta:
# # # # # # # # #                         # Get content from delta
# # # # # # # # #                         token = getattr(delta, 'content', '')
# # # # # # # # #                         if token:
# # # # # # # # #                             full_response += token
# # # # # # # # #                             message_placeholder.markdown(full_response + "▌")
# # # # # # # # #             message_placeholder.markdown(full_response)
# # # # # # # # #         except Exception as e:
# # # # # # # # #             st.error("An error occurred while generating the response.")
# # # # # # # # #             logging.error(f"API Error: {e}")
# # # # # # # # #             full_response = "I'm sorry, but I'm unable to process your request at the moment."

# # # # # # # # #     st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # # # # #     # Save the conversation after each assistant response
# # # # # # # # #     save_conversation(st.session_state.messages)




# # # # # # # # import os
# # # # # # # # import json
# # # # # # # # import datetime
# # # # # # # # import logging  # For logging
# # # # # # # # import streamlit as st
# # # # # # # # from openai import AzureOpenAI
# # # # # # # # from dotenv import load_dotenv
# # # # # # # # import streamlit_authenticator as stauth
# # # # # # # # import pyotp
# # # # # # # # import qrcode
# # # # # # # # import io
# # # # # # # # from io import BytesIO
# # # # # # # # from azure.storage.blob import BlobServiceClient
# # # # # # # # from yaml.loader import SafeLoader
# # # # # # # # import yaml

# # # # # # # # # Load environment variables
# # # # # # # # load_dotenv()

# # # # # # # # # Set up logging to display on the command line
# # # # # # # # logging.basicConfig(
# # # # # # # #     level=logging.ERROR,
# # # # # # # #     format='%(asctime)s %(levelname)s %(message)s'
# # # # # # # # )

# # # # # # # # # Azure OpenAI configuration
# # # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # # st.set_page_config(
# # # # # # # #     page_title="SynoGPT",
# # # # # # # #     page_icon="🤖",
# # # # # # # #     layout="wide",
# # # # # # # #     initial_sidebar_state="auto"
# # # # # # # # )

# # # # # # # # # Initialize the Azure OpenAI client with error handling
# # # # # # # # try:
# # # # # # # #     client = AzureOpenAI(
# # # # # # # #         api_key=azure_openai_api_key,
# # # # # # # #         azure_endpoint=azure_endpoint,
# # # # # # # #         api_version="2024-04-01-preview",
# # # # # # # #     )
# # # # # # # # except Exception as e:
# # # # # # # #     st.error("Failed to initialize Azure OpenAI client.")
# # # # # # # #     logging.error(f"OpenAI Client Initialization Error: {e}")
# # # # # # # #     st.stop()

# # # # # # # # # Load config from Azure Blob Storage
# # # # # # # # connection_string = os.getenv("BLOB_CONNECTION_STRING")
# # # # # # # # container_name = "itgluecopilot"
# # # # # # # # config_blob_name = "config/config_quad.yaml"

# # # # # # # # # BlobServiceClient
# # # # # # # # blob_service_client = BlobServiceClient.from_connection_string(connection_string)
# # # # # # # # container_client = blob_service_client.get_container_client(container_name)

# # # # # # # # # Load the YAML configuration file
# # # # # # # # blob_client = container_client.get_blob_client(config_blob_name)
# # # # # # # # blob_data = blob_client.download_blob().readall()
# # # # # # # # config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# # # # # # # # # Initialize the authenticator
# # # # # # # # authenticator = stauth.Authenticate(
# # # # # # # #     config['credentials'],
# # # # # # # #     config['cookie']['name'],
# # # # # # # #     config['cookie']['key'],
# # # # # # # #     config['cookie']['expiry_days'],
# # # # # # # # )

# # # # # # # # # Function to handle user authentication
# # # # # # # # def authenticate_user():
# # # # # # # #     # Authentication widget
# # # # # # # #     with st.sidebar:
# # # # # # # #         name, authentication_status, username = authenticator.login('Login', 'main')

# # # # # # # #     # Handle authentication status
# # # # # # # #     if authentication_status:
# # # # # # # #         st.session_state["authentication_status"] = True
# # # # # # # #         st.session_state["name"] = name
# # # # # # # #         st.session_state["username"] = username

# # # # # # # #         # Get user data
# # # # # # # #         user_data = config['credentials']['usernames'][username]
# # # # # # # #         user_role = user_data.get('role', 'viewer')  # Default to 'viewer' if not specified
# # # # # # # #         st.session_state['user_role'] = user_role

# # # # # # # #         # Check for OTP secret
# # # # # # # #         otp_secret = user_data.get('otp_secret', "")

# # # # # # # #         if not otp_secret:
# # # # # # # #             # Generate new OTP secret
# # # # # # # #             otp_secret = pyotp.random_base32()
# # # # # # # #             config['credentials']['usernames'][username]['otp_secret'] = otp_secret
# # # # # # # #             # Save updated config back to Blob Storage
# # # # # # # #             blob_client.upload_blob(yaml.dump(config), overwrite=True)
# # # # # # # #             st.session_state['otp_setup_complete'] = False
# # # # # # # #             st.session_state['show_qr_code'] = True
# # # # # # # #             logging.info("Generated new OTP secret for user %s", username)
# # # # # # # #         else:
# # # # # # # #             st.session_state['otp_setup_complete'] = True

# # # # # # # #         # Initialize TOTP
# # # # # # # #         totp = pyotp.TOTP(otp_secret)
# # # # # # # #         logging.info("Using OTP secret for user %s", username)

# # # # # # # #         # Handle OTP verification
# # # # # # # #         if not st.session_state.get('otp_verified', False):
# # # # # # # #             if st.session_state.get('show_qr_code', False):
# # # # # # # #                 st.title("Welcome! 👋")
# # # # # # # #                 otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoGPT")
# # # # # # # #                 qr = qrcode.make(otp_uri)
# # # # # # # #                 qr = qr.resize((200, 200))
# # # # # # # #                 st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: GoogleAuth)")

# # # # # # # #             otp_input = st.text_input("Enter the OTP from your authenticator app", type="password")
# # # # # # # #             verify_button_clicked = st.button("Verify OTP")

# # # # # # # #             if verify_button_clicked:
# # # # # # # #                 if totp.verify(otp_input):
# # # # # # # #                     st.session_state['otp_verified'] = True
# # # # # # # #                     st.session_state['show_qr_code'] = False
# # # # # # # #                     st.success(f'Welcome *{name}*')
# # # # # # # #                     logging.info("User %s authenticated successfully with 2FA", username)
# # # # # # # #                     # Proceed to the main app
# # # # # # # #                     return True
# # # # # # # #                 else:
# # # # # # # #                     st.error("Invalid OTP. Please try again.")
# # # # # # # #                     logging.warning("Invalid OTP attempt for user %s", username)
# # # # # # # #                     return False
# # # # # # # #         else:
# # # # # # # #             # User is already verified
# # # # # # # #             st.success(f'Welcome back *{name}*')
# # # # # # # #             logging.info("User %s re-authenticated successfully", username)
# # # # # # # #             return True

# # # # # # # #     elif authentication_status == False:
# # # # # # # #         st.sidebar.error('Username/password is incorrect')
# # # # # # # #         st.write("# Welcome! 👋")
# # # # # # # #         st.markdown("Please enter your username and password to log in.")
# # # # # # # #         logging.warning("Failed login attempt with username: %s", username)
# # # # # # # #         return False

# # # # # # # #     elif authentication_status == None:
# # # # # # # #         st.sidebar.warning('Please enter your username and password')
# # # # # # # #         st.write("# Welcome! 👋")
# # # # # # # #         st.markdown("Please enter your username and password to log in.")
# # # # # # # #         return False

# # # # # # # # # Call the authenticate_user function
# # # # # # # # if authenticate_user():
# # # # # # # #     # User is authenticated, proceed with the main app code

# # # # # # # #     st.title("SynoGPT! 🤖")

# # # # # # # #     with st.sidebar:
# # # # # # # #         st.image(r"./synoptek.png", width=275)
# # # # # # # #         # Logout button
# # # # # # # #         if st.button("Logout"):
# # # # # # # #             authenticator.logout('Logout', 'sidebar')
# # # # # # # #             for key in list(st.session_state.keys()):
# # # # # # # #                 del st.session_state[key]
# # # # # # # #             st.rerun()

# # # # # # # #     # Path to the conversations file
# # # # # # # #     CONVERSATIONS_FILE = "conversations.json"

# # # # # # # #     # Function to load conversations from file with error handling
# # # # # # # #     def load_conversations():
# # # # # # # #         try:
# # # # # # # #             if os.path.exists(CONVERSATIONS_FILE):
# # # # # # # #                 with open(CONVERSATIONS_FILE, "r") as f:
# # # # # # # #                     return json.load(f)
# # # # # # # #             else:
# # # # # # # #                 return []
# # # # # # # #         except Exception as e:
# # # # # # # #             st.error("Failed to load conversations.")
# # # # # # # #             logging.error(f"Load Conversations Error: {e}")
# # # # # # # #             return []

# # # # # # # #     # Function to save a conversation with error handling
# # # # # # # #     def save_conversation(conversation):
# # # # # # # #         try:
# # # # # # # #             conversations = load_conversations()
# # # # # # # #             # Append the new conversation with timestamp
# # # # # # # #             conversations.append({
# # # # # # # #                 "timestamp": datetime.datetime.now().isoformat(),
# # # # # # # #                 "messages": conversation
# # # # # # # #             })
# # # # # # # #             # Limit to the most recent 30 conversations
# # # # # # # #             conversations = conversations[-30:]
# # # # # # # #             with open(CONVERSATIONS_FILE, "w") as f:
# # # # # # # #                 json.dump(conversations, f, indent=4)
# # # # # # # #         except Exception as e:
# # # # # # # #             st.error("Failed to save conversation.")
# # # # # # # #             logging.error(f"Save Conversation Error: {e}")

# # # # # # # #     # Function to generate a title from the first user message
# # # # # # # #     def get_conversation_title(conversation):
# # # # # # # #         for msg in conversation["messages"]:
# # # # # # # #             if msg["role"] == "user":
# # # # # # # #                 title = msg["content"].strip()
# # # # # # # #                 # Truncate title if it's too long
# # # # # # # #                 return title[:28] + "..." if len(title) > 28 else title
# # # # # # # #         return "Untitled Conversation"

# # # # # # # #     # Sidebar to display conversations
# # # # # # # #     def display_sidebar():
# # # # # # # #         st.sidebar.title("Conversations")

# # # # # # # #         # Add "New Chat" button at the top
# # # # # # # #         if st.sidebar.button("New Chat"):
# # # # # # # #             st.session_state.messages = []
# # # # # # # #             st.rerun()

# # # # # # # #         conversations = load_conversations()

# # # # # # # #         # Categorize conversations
# # # # # # # #         today = []
# # # # # # # #         yesterday = []
# # # # # # # #         previous_7_days = []
# # # # # # # #         previous_30_days = []

# # # # # # # #         now = datetime.datetime.now()
# # # # # # # #         for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # # # # #             try:
# # # # # # # #                 timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # # # # #                 delta = now - timestamp
# # # # # # # #                 if delta.days == 0:
# # # # # # # #                     today.append((idx, convo))
# # # # # # # #                 elif delta.days == 1:
# # # # # # # #                     yesterday.append((idx, convo))
# # # # # # # #                 elif delta.days <= 7:
# # # # # # # #                     previous_7_days.append((idx, convo))
# # # # # # # #                 elif delta.days <= 30:
# # # # # # # #                     previous_30_days.append((idx, convo))
# # # # # # # #             except Exception as e:
# # # # # # # #                 logging.error(f"Error processing conversation timestamp: {e}")

# # # # # # # #         # Display categories
# # # # # # # #         if today:
# # # # # # # #             st.sidebar.subheader("Today")
# # # # # # # #             for idx, convo in today:
# # # # # # # #                 title = get_conversation_title(convo)
# # # # # # # #                 if st.sidebar.button(title, key=f"today_{idx}"):
# # # # # # # #                     st.session_state.messages = convo["messages"]
# # # # # # # #                     st.rerun()

# # # # # # # #         if yesterday:
# # # # # # # #             st.sidebar.subheader("Yesterday")
# # # # # # # #             for idx, convo in yesterday:
# # # # # # # #                 title = get_conversation_title(convo)
# # # # # # # #                 if st.sidebar.button(title, key=f"yesterday_{idx}"):
# # # # # # # #                     st.session_state.messages = convo["messages"]
# # # # # # # #                     st.rerun()

# # # # # # # #         if previous_7_days:
# # # # # # # #             st.sidebar.subheader("Previous 7 Days")
# # # # # # # #             for idx, convo in previous_7_days:
# # # # # # # #                 title = get_conversation_title(convo)
# # # # # # # #                 if st.sidebar.button(title, key=f"week_{idx}"):
# # # # # # # #                     st.session_state.messages = convo["messages"]
# # # # # # # #                     st.rerun()

# # # # # # # #         if previous_30_days:
# # # # # # # #             st.sidebar.subheader("Previous 30 Days")
# # # # # # # #             for idx, convo in previous_30_days:
# # # # # # # #                 title = get_conversation_title(convo)
# # # # # # # #                 if st.sidebar.button(title, key=f"month_{idx}"):
# # # # # # # #                     st.session_state.messages = convo["messages"]
# # # # # # # #                     st.rerun()

# # # # # # # #     # Call the sidebar function
# # # # # # # #     display_sidebar()

# # # # # # # #     # Initialize session state for messages and model
# # # # # # # #     if "messages" not in st.session_state:
# # # # # # # #         st.session_state.messages = []

# # # # # # # #     if "model" not in st.session_state:
# # # # # # # #         st.session_state.model = "gpt-4o"

# # # # # # # #     # Display previous chat messages
# # # # # # # #     for message in st.session_state["messages"]:
# # # # # # # #         with st.chat_message(message["role"]):
# # # # # # # #             st.markdown(message["content"])

# # # # # # # #     # User input
# # # # # # # #     if user_prompt := st.chat_input("Type here to Chat..."):
# # # # # # # #         st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # # #         with st.chat_message("user"):
# # # # # # # #             st.markdown(user_prompt)

# # # # # # # #         # Generate responses with error handling
# # # # # # # #         with st.chat_message("assistant"):
# # # # # # # #             message_placeholder = st.empty()
# # # # # # # #             full_response = ""

# # # # # # # #             try:
# # # # # # # #                 stream = client.chat.completions.create(
# # # # # # # #                     model=st.session_state.model,
# # # # # # # #                     messages=st.session_state.messages,
# # # # # # # #                     stream=True,
# # # # # # # #                     max_tokens=4000,
# # # # # # # #                     temperature=0.2,
# # # # # # # #                 )
# # # # # # # #                 for chunk in stream:
# # # # # # # #                     # Access choices as an attribute
# # # # # # # #                     choices = getattr(chunk, 'choices', None)
# # # # # # # #                     if choices:
# # # # # # # #                         # Access the first choice
# # # # # # # #                         choice = choices[0]
# # # # # # # #                         # Access delta as an attribute
# # # # # # # #                         delta = getattr(choice, 'delta', None)
# # # # # # # #                         if delta:
# # # # # # # #                             # Get content from delta
# # # # # # # #                             token = getattr(delta, 'content', '')
# # # # # # # #                             if token:
# # # # # # # #                                 full_response += token
# # # # # # # #                                 message_placeholder.markdown(full_response + "▌")
# # # # # # # #                 message_placeholder.markdown(full_response)
# # # # # # # #             except Exception as e:
# # # # # # # #                 st.error("An error occurred while generating the response.")
# # # # # # # #                 logging.error(f"API Error: {e}")
# # # # # # # #                 full_response = "I'm sorry, but I'm unable to process your request at the moment."

# # # # # # # #         st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # # # #         # Save the conversation after each assistant response
# # # # # # # #         save_conversation(st.session_state.messages)

# # # # # # # # else:
# # # # # # # #     # Stop the app if not authenticated
# # # # # # # #     st.stop()



# # # # # # # import os
# # # # # # # import json
# # # # # # # import datetime
# # # # # # # import logging  # For logging
# # # # # # # import streamlit as st
# # # # # # # from openai import AzureOpenAI
# # # # # # # from dotenv import load_dotenv
# # # # # # # import streamlit_authenticator as stauth
# # # # # # # import pyotp
# # # # # # # import qrcode
# # # # # # # import io
# # # # # # # from io import BytesIO
# # # # # # # from azure.storage.blob import BlobServiceClient
# # # # # # # from yaml.loader import SafeLoader
# # # # # # # import yaml

# # # # # # # # Load environment variables
# # # # # # # load_dotenv()

# # # # # # # # Set up logging to display on the command line
# # # # # # # logging.basicConfig(
# # # # # # #     level=logging.ERROR,
# # # # # # #     format='%(asctime)s %(levelname)s %(message)s'
# # # # # # # )

# # # # # # # # Azure OpenAI configuration
# # # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # # st.set_page_config(
# # # # # # #     page_title="SynoGPT",
# # # # # # #     page_icon="🤖",
# # # # # # #     layout="wide",
# # # # # # #     initial_sidebar_state="auto"
# # # # # # # )

# # # # # # # # Initialize the Azure OpenAI client with error handling
# # # # # # # try:
# # # # # # #     client = AzureOpenAI(
# # # # # # #         api_key=azure_openai_api_key,
# # # # # # #         azure_endpoint=azure_endpoint,
# # # # # # #         api_version="2024-04-01-preview",
# # # # # # #     )
# # # # # # # except Exception as e:
# # # # # # #     st.error("Failed to initialize Azure OpenAI client.")
# # # # # # #     logging.error(f"OpenAI Client Initialization Error: {e}")
# # # # # # #     st.stop()

# # # # # # # # Load config from Azure Blob Storage
# # # # # # # connection_string = os.getenv("BLOB_CONNECTION_STRING")
# # # # # # # container_name = "itgluecopilot"
# # # # # # # config_blob_name = "config/config_quad.yaml"

# # # # # # # # BlobServiceClient
# # # # # # # blob_service_client = BlobServiceClient.from_connection_string(connection_string)
# # # # # # # container_client = blob_service_client.get_container_client(container_name)

# # # # # # # # Load the YAML configuration file
# # # # # # # blob_client = container_client.get_blob_client(config_blob_name)
# # # # # # # blob_data = blob_client.download_blob().readall()
# # # # # # # config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# # # # # # # # Initialize the authenticator
# # # # # # # authenticator = stauth.Authenticate(
# # # # # # #     config['credentials'],
# # # # # # #     config['cookie']['name'],
# # # # # # #     config['cookie']['key'],
# # # # # # #     config['cookie']['expiry_days'],
# # # # # # # )

# # # # # # # # Sidebar code
# # # # # # # with st.sidebar:
# # # # # # #     st.image(r"./synoptek.png", width=275)
# # # # # # #     # Authentication widget
# # # # # # #     name, authentication_status, username = authenticator.login('Login', 'sidebar')

# # # # # # #     if authentication_status:
# # # # # # #         # Display conversations in the sidebar after authentication
# # # # # # #         st.title("Conversations")

# # # # # # #         # Add "New Chat" button at the top
# # # # # # #         if st.button("New Chat"):
# # # # # # #             st.session_state.messages = []
# # # # # # #             st.rerun()

# # # # # # #         # Functions to load and display conversations
# # # # # # #         def load_conversations():
# # # # # # #             try:
# # # # # # #                 if os.path.exists("conversations.json"):
# # # # # # #                     with open("conversations.json", "r") as f:
# # # # # # #                         return json.load(f)
# # # # # # #                 else:
# # # # # # #                     return []
# # # # # # #             except Exception as e:
# # # # # # #                 st.error("Failed to load conversations.")
# # # # # # #                 logging.error(f"Load Conversations Error: {e}")
# # # # # # #                 return []

# # # # # # #         def get_conversation_title(conversation):
# # # # # # #             for msg in conversation["messages"]:
# # # # # # #                 if msg["role"] == "user":
# # # # # # #                     title = msg["content"].strip()
# # # # # # #                     # Truncate title if it's too long
# # # # # # #                     return title[:28] + "..." if len(title) > 28 else title
# # # # # # #             return "Untitled Conversation"

# # # # # # #         conversations = load_conversations()

# # # # # # #         # Categorize conversations
# # # # # # #         today = []
# # # # # # #         yesterday = []
# # # # # # #         previous_7_days = []
# # # # # # #         previous_30_days = []

# # # # # # #         now = datetime.datetime.now()
# # # # # # #         for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # # # #             try:
# # # # # # #                 timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # # # #                 delta = now - timestamp
# # # # # # #                 if delta.days == 0:
# # # # # # #                     today.append((idx, convo))
# # # # # # #                 elif delta.days == 1:
# # # # # # #                     yesterday.append((idx, convo))
# # # # # # #                 elif delta.days <= 7:
# # # # # # #                     previous_7_days.append((idx, convo))
# # # # # # #                 elif delta.days <= 30:
# # # # # # #                     previous_30_days.append((idx, convo))
# # # # # # #             except Exception as e:
# # # # # # #                 logging.error(f"Error processing conversation timestamp: {e}")

# # # # # # #         # Display categories
# # # # # # #         if today:
# # # # # # #             st.subheader("Today")
# # # # # # #             for idx, convo in today:
# # # # # # #                 title = get_conversation_title(convo)
# # # # # # #                 if st.button(title, key=f"today_{idx}"):
# # # # # # #                     st.session_state.messages = convo["messages"]
# # # # # # #                     st.rerun()

# # # # # # #         if yesterday:
# # # # # # #             st.subheader("Yesterday")
# # # # # # #             for idx, convo in yesterday:
# # # # # # #                 title = get_conversation_title(convo)
# # # # # # #                 if st.button(title, key=f"yesterday_{idx}"):
# # # # # # #                     st.session_state.messages = convo["messages"]
# # # # # # #                     st.rerun()

# # # # # # #         if previous_7_days:
# # # # # # #             st.subheader("Previous 7 Days")
# # # # # # #             for idx, convo in previous_7_days:
# # # # # # #                 title = get_conversation_title(convo)
# # # # # # #                 if st.button(title, key=f"week_{idx}"):
# # # # # # #                     st.session_state.messages = convo["messages"]
# # # # # # #                     st.rerun()

# # # # # # #         if previous_30_days:
# # # # # # #             st.subheader("Previous 30 Days")
# # # # # # #             for idx, convo in previous_30_days:
# # # # # # #                 title = get_conversation_title(convo)
# # # # # # #                 if st.button(title, key=f"month_{idx}"):
# # # # # # #                     st.session_state.messages = convo["messages"]
# # # # # # #                     st.rerun()

# # # # # # #         # Add vertical space to push the welcome message and logout button to the bottom
# # # # # # #         st.markdown("<br><br><br><br><br><br>", unsafe_allow_html=True)

# # # # # # #         # Welcome message and logout button at the bottom
# # # # # # #         st.markdown("---")
# # # # # # #         st.markdown(f'## Hello, *{name}*')
# # # # # # #         if st.button("Logout"):
# # # # # # #             authenticator.logout('Logout', 'sidebar')
# # # # # # #             for key in list(st.session_state.keys()):
# # # # # # #                 del st.session_state[key]
# # # # # # #             st.rerun()
# # # # # # #     elif authentication_status == False:
# # # # # # #         st.error('Username/password is incorrect')
# # # # # # #     elif authentication_status == None:
# # # # # # #         st.warning('Please enter your username and password')

# # # # # # # # Function to handle user authentication
# # # # # # # def authenticate_user(authentication_status, name, username):
# # # # # # #     # Handle authentication status
# # # # # # #     if authentication_status:
# # # # # # #         st.session_state["authentication_status"] = True
# # # # # # #         st.session_state["name"] = name
# # # # # # #         st.session_state["username"] = username

# # # # # # #         # Get user data
# # # # # # #         user_data = config['credentials']['usernames'][username]
# # # # # # #         user_role = user_data.get('role', 'viewer')  # Default to 'viewer' if not specified
# # # # # # #         st.session_state['user_role'] = user_role

# # # # # # #         # Check for OTP secret
# # # # # # #         otp_secret = user_data.get('otp_secret', "")

# # # # # # #         if not otp_secret:
# # # # # # #             # Generate new OTP secret
# # # # # # #             otp_secret = pyotp.random_base32()
# # # # # # #             config['credentials']['usernames'][username]['otp_secret'] = otp_secret
# # # # # # #             # Save updated config back to Blob Storage
# # # # # # #             blob_client.upload_blob(yaml.dump(config), overwrite=True)
# # # # # # #             st.session_state['otp_setup_complete'] = False
# # # # # # #             st.session_state['show_qr_code'] = True
# # # # # # #             logging.info("Generated new OTP secret for user %s", username)
# # # # # # #         else:
# # # # # # #             st.session_state['otp_setup_complete'] = True

# # # # # # #         # Initialize TOTP
# # # # # # #         totp = pyotp.TOTP(otp_secret)
# # # # # # #         logging.info("Using OTP secret for user %s", username)

# # # # # # #         # Handle OTP verification
# # # # # # #         if not st.session_state.get('otp_verified', False):
# # # # # # #             if st.session_state.get('show_qr_code', False):
# # # # # # #                 st.title("Welcome! 👋")
# # # # # # #                 otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoGPT")
# # # # # # #                 qr = qrcode.make(otp_uri)
# # # # # # #                 qr = qr.resize((200, 200))
# # # # # # #                 st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: Google Authenticator)")

# # # # # # #             otp_input = st.text_input("Enter the OTP from your authenticator app", type="password")
# # # # # # #             verify_button_clicked = st.button("Verify OTP")

# # # # # # #             if verify_button_clicked:
# # # # # # #                 if totp.verify(otp_input):
# # # # # # #                     st.session_state['otp_verified'] = True
# # # # # # #                     st.session_state['show_qr_code'] = False
# # # # # # #                     st.success(f'Welcome *{name}*')
# # # # # # #                     logging.info("User %s authenticated successfully with 2FA", username)
# # # # # # #                     # Proceed to the main app
# # # # # # #                     return True
# # # # # # #                 else:
# # # # # # #                     st.error("Invalid OTP. Please try again.")
# # # # # # #                     logging.warning("Invalid OTP attempt for user %s", username)
# # # # # # #                     return False
# # # # # # #         else:
# # # # # # #             # User is already verified
# # # # # # #             st.success(f'Welcome back *{name}*')
# # # # # # #             logging.info("User %s re-authenticated successfully", username)
# # # # # # #             return True

# # # # # # #     elif authentication_status == False:
# # # # # # #         st.write("# Welcome! 👋")
# # # # # # #         st.markdown("Please enter your username and password to log in.")
# # # # # # #         logging.warning("Failed login attempt with username: %s", username)
# # # # # # #         return False

# # # # # # #     elif authentication_status == None:
# # # # # # #         st.write("# Welcome! 👋")
# # # # # # #         st.markdown("Please enter your username and password to log in.")
# # # # # # #         return False

# # # # # # # # Call the authenticate_user function
# # # # # # # if authenticate_user(authentication_status, name, username):
# # # # # # #     # User is authenticated, proceed with the main app code

# # # # # # #     st.title("SynoGPT! 🤖")

# # # # # # #     # Initialize session state for messages and model
# # # # # # #     if "messages" not in st.session_state:
# # # # # # #         st.session_state.messages = []

# # # # # # #     if "model" not in st.session_state:
# # # # # # #         st.session_state.model = "gpt-4o"

# # # # # # #     # Display previous chat messages
# # # # # # #     for message in st.session_state["messages"]:
# # # # # # #         with st.chat_message(message["role"]):
# # # # # # #             st.markdown(message["content"])

# # # # # # #     # User input
# # # # # # #     if user_prompt := st.chat_input("Type here to Chat..."):
# # # # # # #         st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # # #         with st.chat_message("user"):
# # # # # # #             st.markdown(user_prompt)

# # # # # # #         # Function to save a conversation with error handling
# # # # # # #         def save_conversation(conversation):
# # # # # # #             try:
# # # # # # #                 conversations = load_conversations()
# # # # # # #                 # Append the new conversation with timestamp
# # # # # # #                 conversations.append({
# # # # # # #                     "timestamp": datetime.datetime.now().isoformat(),
# # # # # # #                     "messages": conversation
# # # # # # #                 })
# # # # # # #                 # Limit to the most recent 30 conversations
# # # # # # #                 conversations = conversations[-30:]
# # # # # # #                 with open("conversations.json", "w") as f:
# # # # # # #                     json.dump(conversations, f, indent=4)
# # # # # # #             except Exception as e:
# # # # # # #                 st.error("Failed to save conversation.")
# # # # # # #                 logging.error(f"Save Conversation Error: {e}")

# # # # # # #         # Generate responses with error handling
# # # # # # #         with st.chat_message("assistant"):
# # # # # # #             message_placeholder = st.empty()
# # # # # # #             full_response = ""

# # # # # # #             try:
# # # # # # #                 stream = client.chat.completions.create(
# # # # # # #                     model=st.session_state.model,
# # # # # # #                     messages=st.session_state.messages,
# # # # # # #                     stream=True,
# # # # # # #                     max_tokens=4000,
# # # # # # #                     temperature=0.2,
# # # # # # #                 )
# # # # # # #                 for chunk in stream:
# # # # # # #                     # Access choices as an attribute
# # # # # # #                     choices = getattr(chunk, 'choices', None)
# # # # # # #                     if choices:
# # # # # # #                         # Access the first choice
# # # # # # #                         choice = choices[0]
# # # # # # #                         # Access delta as an attribute
# # # # # # #                         delta = getattr(choice, 'delta', None)
# # # # # # #                         if delta:
# # # # # # #                             # Get content from delta
# # # # # # #                             token = getattr(delta, 'content', '')
# # # # # # #                             if token:
# # # # # # #                                 full_response += token
# # # # # # #                                 message_placeholder.markdown(full_response + "▌")
# # # # # # #                 message_placeholder.markdown(full_response)
# # # # # # #             except Exception as e:
# # # # # # #                 st.error("An error occurred while generating the response.")
# # # # # # #                 logging.error(f"API Error: {e}")
# # # # # # #                 full_response = "I'm sorry, but I'm unable to process your request at the moment."

# # # # # # #         st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # # #         # Save the conversation after each assistant response
# # # # # # #         save_conversation(st.session_state.messages)

# # # # # # # else:
# # # # # # #     # Stop the app if not authenticated
# # # # # # #     st.stop()


# # # # # # import os
# # # # # # import json
# # # # # # import datetime
# # # # # # import logging  # For logging
# # # # # # import streamlit as st
# # # # # # from openai import AzureOpenAI
# # # # # # from dotenv import load_dotenv
# # # # # # import streamlit_authenticator as stauth
# # # # # # import pyotp
# # # # # # import qrcode
# # # # # # import io
# # # # # # from io import BytesIO
# # # # # # from azure.storage.blob import BlobServiceClient
# # # # # # from yaml.loader import SafeLoader
# # # # # # import yaml

# # # # # # # Load environment variables
# # # # # # load_dotenv()

# # # # # # # Set up logging to display on the command line
# # # # # # logging.basicConfig(
# # # # # #     level=logging.ERROR,
# # # # # #     format='%(asctime)s %(levelname)s %(message)s'
# # # # # # )

# # # # # # # Azure OpenAI configuration
# # # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # # st.set_page_config(
# # # # # #     page_title="SynoptekGPT",
# # # # # #     page_icon="🤖",
# # # # # #     layout="wide",
# # # # # #     initial_sidebar_state="auto"
# # # # # # )

# # # # # # # Initialize the Azure OpenAI client with error handling
# # # # # # try:
# # # # # #     client = AzureOpenAI(
# # # # # #         api_key=azure_openai_api_key,
# # # # # #         azure_endpoint=azure_endpoint,
# # # # # #         api_version="2024-04-01-preview",
# # # # # #     )
# # # # # # except Exception as e:
# # # # # #     st.error("Failed to initialize Azure OpenAI client.")
# # # # # #     logging.error(f"OpenAI Client Initialization Error: {e}")
# # # # # #     st.stop()

# # # # # # # Load config from Azure Blob Storage
# # # # # # connection_string = os.getenv("BLOB_CONNECTION_STRING")
# # # # # # container_name = "itgluecopilot"
# # # # # # config_blob_name = "config/config_quad.yaml"

# # # # # # # BlobServiceClient
# # # # # # blob_service_client = BlobServiceClient.from_connection_string(connection_string)
# # # # # # container_client = blob_service_client.get_container_client(container_name)

# # # # # # # Load the YAML configuration file
# # # # # # blob_client = container_client.get_blob_client(config_blob_name)
# # # # # # blob_data = blob_client.download_blob().readall()
# # # # # # config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# # # # # # # Initialize the authenticator
# # # # # # authenticator = stauth.Authenticate(
# # # # # #     config['credentials'],
# # # # # #     config['cookie']['name'],
# # # # # #     config['cookie']['key'],
# # # # # #     config['cookie']['expiry_days'],
# # # # # # )

# # # # # # # Sidebar code
# # # # # # with st.sidebar:
# # # # # #     st.image(r"./synoptek.png", width=275)
# # # # # #     # Authentication widget
# # # # # #     name, authentication_status, username = authenticator.login('Login', 'sidebar')

# # # # # #     if authentication_status:
# # # # # #         # Display conversations in the sidebar after authentication
# # # # # #         st.title("Conversations")

# # # # # #         # Add "New Chat" button at the top with a unique key
# # # # # #         if st.button("New Chat", key='new_chat_button'):
# # # # # #             st.session_state.messages = []
# # # # # #             st.rerun()

# # # # # #         # Functions to load and display conversations
# # # # # #         def load_conversations():
# # # # # #             try:
# # # # # #                 if os.path.exists("conversations.json"):
# # # # # #                     with open("conversations.json", "r") as f:
# # # # # #                         return json.load(f)
# # # # # #                 else:
# # # # # #                     return []
# # # # # #             except Exception as e:
# # # # # #                 st.error("Failed to load conversations.")
# # # # # #                 logging.error(f"Load Conversations Error: {e}")
# # # # # #                 return []

# # # # # #         def get_conversation_title(conversation):
# # # # # #             for msg in conversation["messages"]:
# # # # # #                 if msg["role"] == "user":
# # # # # #                     title = msg["content"].strip()
# # # # # #                     # Truncate title if it's too long
# # # # # #                     return title[:28] + "..." if len(title) > 28 else title
# # # # # #             return "Untitled Conversation"

# # # # # #         conversations = load_conversations()

# # # # # #         # Categorize conversations
# # # # # #         today = []
# # # # # #         yesterday = []
# # # # # #         previous_7_days = []
# # # # # #         previous_30_days = []

# # # # # #         now = datetime.datetime.now()
# # # # # #         for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # # #             try:
# # # # # #                 timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # # #                 delta = now - timestamp
# # # # # #                 if delta.days == 0:
# # # # # #                     today.append((idx, convo))
# # # # # #                 elif delta.days == 1:
# # # # # #                     yesterday.append((idx, convo))
# # # # # #                 elif delta.days <= 7:
# # # # # #                     previous_7_days.append((idx, convo))
# # # # # #                 elif delta.days <= 30:
# # # # # #                     previous_30_days.append((idx, convo))
# # # # # #             except Exception as e:
# # # # # #                 logging.error(f"Error processing conversation timestamp: {e}")

# # # # # #         # Display categories
# # # # # #         if today:
# # # # # #             st.subheader("Today")
# # # # # #             for idx, convo in today:
# # # # # #                 title = get_conversation_title(convo)
# # # # # #                 if st.button(title, key=f"today_{idx}"):
# # # # # #                     st.session_state.messages = convo["messages"]
# # # # # #                     st.rerun()

# # # # # #         if yesterday:
# # # # # #             st.subheader("Yesterday")
# # # # # #             for idx, convo in yesterday:
# # # # # #                 title = get_conversation_title(convo)
# # # # # #                 if st.button(title, key=f"yesterday_{idx}"):
# # # # # #                     st.session_state.messages = convo["messages"]
# # # # # #                     st.rerun()

# # # # # #         if previous_7_days:
# # # # # #             st.subheader("Previous 7 Days")
# # # # # #             for idx, convo in previous_7_days:
# # # # # #                 title = get_conversation_title(convo)
# # # # # #                 if st.button(title, key=f"week_{idx}"):
# # # # # #                     st.session_state.messages = convo["messages"]
# # # # # #                     st.rerun()

# # # # # #         if previous_30_days:
# # # # # #             st.subheader("Previous 30 Days")
# # # # # #             for idx, convo in previous_30_days:
# # # # # #                 title = get_conversation_title(convo)
# # # # # #                 if st.button(title, key=f"month_{idx}"):
# # # # # #                     st.session_state.messages = convo["messages"]
# # # # # #                     st.rerun()

# # # # # #         # Add vertical space to push the welcome message and logout button to the bottom
# # # # # #         st.markdown("<br><br><br><br><br><br>", unsafe_allow_html=True)

# # # # # #         # Welcome message and logout button at the bottom
# # # # # #         st.markdown("---")
# # # # # #         st.markdown(f'## Hello, *{name}*')
# # # # # #         if st.button("Logout", key='logout_button'):
# # # # # #             authenticator.logout('Logout', 'sidebar')
# # # # # #             for key in list(st.session_state.keys()):
# # # # # #                 del st.session_state[key]
# # # # # #             st.rerun()
# # # # # #     elif authentication_status == False:
# # # # # #         st.error('Username/password is incorrect')
# # # # # #     elif authentication_status == None:
# # # # # #         st.warning('Please enter your username and password')

# # # # # # # Function to handle user authentication
# # # # # # def authenticate_user(authentication_status, name, username):
# # # # # #     # Handle authentication status
# # # # # #     if authentication_status:
# # # # # #         st.session_state["authentication_status"] = True
# # # # # #         st.session_state["name"] = name
# # # # # #         st.session_state["username"] = username

# # # # # #         # Get user data
# # # # # #         user_data = config['credentials']['usernames'][username]
# # # # # #         user_role = user_data.get('role', 'viewer')  # Default to 'viewer' if not specified
# # # # # #         st.session_state['user_role'] = user_role

# # # # # #         # Check for OTP secret
# # # # # #         otp_secret = user_data.get('otp_secret', "")

# # # # # #         if not otp_secret:
# # # # # #             # Generate new OTP secret
# # # # # #             otp_secret = pyotp.random_base32()
# # # # # #             config['credentials']['usernames'][username]['otp_secret'] = otp_secret
# # # # # #             # Save updated config back to Blob Storage
# # # # # #             blob_client.upload_blob(yaml.dump(config), overwrite=True)
# # # # # #             st.session_state['otp_setup_complete'] = False
# # # # # #             st.session_state['show_qr_code'] = True
# # # # # #             logging.info("Generated new OTP secret for user %s", username)
# # # # # #         else:
# # # # # #             st.session_state['otp_setup_complete'] = True

# # # # # #         # Initialize TOTP
# # # # # #         totp = pyotp.TOTP(otp_secret)
# # # # # #         logging.info("Using OTP secret for user %s", username)

# # # # # #         # Handle OTP verification
# # # # # #         if not st.session_state.get('otp_verified', False):
# # # # # #             if st.session_state.get('show_qr_code', False):
# # # # # #                 st.title("Welcome! 👋")
# # # # # #                 otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoGPT")
# # # # # #                 qr = qrcode.make(otp_uri)
# # # # # #                 qr = qr.resize((200, 200))
# # # # # #                 st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: Google Authenticator)")

# # # # # #             st.title("Welcome to SynoptekGPT!")
# # # # # #             otp_input = st.text_input("Enter the OTP from your authenticator app", type="password", key='otp_input')
# # # # # #             verify_button_clicked = st.button("Verify OTP", key='verify_otp_button')

# # # # # #             if verify_button_clicked:
# # # # # #                 if totp.verify(otp_input):
# # # # # #                     st.session_state['otp_verified'] = True
# # # # # #                     st.session_state['show_qr_code'] = False
# # # # # #                     st.success(f'Welcome *{name}*')
# # # # # #                     logging.info("User %s authenticated successfully with 2FA", username)
# # # # # #                     # Proceed to the main app
# # # # # #                     return True
# # # # # #                 else:
# # # # # #                     st.error("Invalid OTP. Please try again.")
# # # # # #                     logging.warning("Invalid OTP attempt for user %s", username)
# # # # # #                     return False
# # # # # #         else:
# # # # # #             # User is already verified
# # # # # #             st.success(f'Welcome back *{name}*')
# # # # # #             logging.info("User %s re-authenticated successfully", username)
# # # # # #             return True

# # # # # #     elif authentication_status == False:
# # # # # #         st.write("# Welcome! 👋")
# # # # # #         st.markdown("Please enter your username and password to log in.")
# # # # # #         logging.warning("Failed login attempt with username: %s", username)
# # # # # #         return False

# # # # # #     elif authentication_status == None:
# # # # # #         st.write("# Welcome! 👋")
# # # # # #         st.markdown("Please enter your username and password to log in.")
# # # # # #         return False

# # # # # # # Call the authenticate_user function
# # # # # # if authenticate_user(authentication_status, name, username):
# # # # # #     # User is authenticated, proceed with the main app code

# # # # # #     st.title("Synoptek-GPT! 🤖")

# # # # # #     # Initialize session state for messages and model
# # # # # #     if "messages" not in st.session_state:
# # # # # #         st.session_state.messages = []

# # # # # #     if "model" not in st.session_state:
# # # # # #         st.session_state.model = "gpt-4o"

# # # # # #     # Display previous chat messages
# # # # # #     for message in st.session_state["messages"]:
# # # # # #         with st.chat_message(message["role"]):
# # # # # #             st.markdown(message["content"])

# # # # # #     # User input
# # # # # #     if user_prompt := st.chat_input("Type here to Chat..."):
# # # # # #         st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # # #         with st.chat_message("user"):
# # # # # #             st.markdown(user_prompt)

# # # # # #         # Function to save a conversation with error handling
# # # # # #         def save_conversation(conversation):
# # # # # #             try:
# # # # # #                 conversations = load_conversations()
# # # # # #                 # Append the new conversation with timestamp
# # # # # #                 conversations.append({
# # # # # #                     "timestamp": datetime.datetime.now().isoformat(),
# # # # # #                     "messages": conversation
# # # # # #                 })
# # # # # #                 # Limit to the most recent 30 conversations
# # # # # #                 conversations = conversations[-30:]
# # # # # #                 with open("conversations.json", "w") as f:
# # # # # #                     json.dump(conversations, f, indent=4)
# # # # # #             except Exception as e:
# # # # # #                 st.error("Failed to save conversation.")
# # # # # #                 logging.error(f"Save Conversation Error: {e}")

# # # # # #         # Generate responses with error handling
# # # # # #         with st.chat_message("assistant"):
# # # # # #             message_placeholder = st.empty()
# # # # # #             full_response = ""

# # # # # #             try:
# # # # # #                 stream = client.chat.completions.create(
# # # # # #                     model=st.session_state.model,
# # # # # #                     messages=st.session_state.messages,
# # # # # #                     stream=True,
# # # # # #                     max_tokens=4000,
# # # # # #                     temperature=0.2,
# # # # # #                 )
# # # # # #                 for chunk in stream:
# # # # # #                     # Access choices as an attribute
# # # # # #                     choices = getattr(chunk, 'choices', None)
# # # # # #                     if choices:
# # # # # #                         # Access the first choice
# # # # # #                         choice = choices[0]
# # # # # #                         # Access delta as an attribute
# # # # # #                         delta = getattr(choice, 'delta', None)
# # # # # #                         if delta:
# # # # # #                             # Get content from delta
# # # # # #                             token = getattr(delta, 'content', '')
# # # # # #                             if token:
# # # # # #                                 full_response += token
# # # # # #                                 message_placeholder.markdown(full_response + "▌")
# # # # # #                 message_placeholder.markdown(full_response)
# # # # # #             except Exception as e:
# # # # # #                 st.error("An error occurred while generating the response.")
# # # # # #                 logging.error(f"API Error: {e}")
# # # # # #                 full_response = "I'm sorry, but I'm unable to process your request at the moment."

# # # # # #         st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # # #         # Save the conversation after each assistant response
# # # # # #         save_conversation(st.session_state.messages)

# # # # # # else:
# # # # # #     # Stop the app if not authenticated
# # # # # #     st.stop()




# # # # # import os
# # # # # import json
# # # # # import datetime
# # # # # import logging  # For logging
# # # # # import streamlit as st
# # # # # from openai import AzureOpenAI
# # # # # from dotenv import load_dotenv
# # # # # import streamlit_authenticator as stauth
# # # # # import pyotp
# # # # # import qrcode
# # # # # import io
# # # # # from io import BytesIO
# # # # # from azure.storage.blob import BlobServiceClient
# # # # # from yaml.loader import SafeLoader
# # # # # import yaml

# # # # # # Load environment variables
# # # # # load_dotenv()

# # # # # # Set up logging to display on the command line
# # # # # logging.basicConfig(
# # # # #     level=logging.ERROR,
# # # # #     format='%(asctime)s %(levelname)s %(message)s'
# # # # # )

# # # # # # Azure OpenAI configuration
# # # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # # st.set_page_config(
# # # # #     page_title="SynoptekGPT",
# # # # #     page_icon="🤖",
# # # # #     layout="wide",
# # # # #     initial_sidebar_state="auto"
# # # # # )

# # # # # # Initialize the Azure OpenAI client with error handling
# # # # # try:
# # # # #     client = AzureOpenAI(
# # # # #         api_key=azure_openai_api_key,
# # # # #         azure_endpoint=azure_endpoint,
# # # # #         api_version="2024-04-01-preview",
# # # # #     )
# # # # # except Exception as e:
# # # # #     st.error("Failed to initialize Azure OpenAI client.")
# # # # #     logging.error(f"OpenAI Client Initialization Error: {e}")
# # # # #     st.stop()

# # # # # # Load config from Azure Blob Storage
# # # # # connection_string = os.getenv("BLOB_CONNECTION_STRING")
# # # # # container_name = "itgluecopilot"
# # # # # config_blob_name = "config/config_quad.yaml"

# # # # # # BlobServiceClient
# # # # # blob_service_client = BlobServiceClient.from_connection_string(connection_string)
# # # # # container_client = blob_service_client.get_container_client(container_name)

# # # # # # Load the YAML configuration file
# # # # # blob_client = container_client.get_blob_client(config_blob_name)
# # # # # blob_data = blob_client.download_blob().readall()
# # # # # config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# # # # # # Initialize the authenticator
# # # # # authenticator = stauth.Authenticate(
# # # # #     config['credentials'],
# # # # #     config['cookie']['name'],
# # # # #     config['cookie']['key'],
# # # # #     config['cookie']['expiry_days'],
# # # # # )

# # # # # # Function to handle user authentication
# # # # # def authenticate_user(authentication_status, name, username):
# # # # #     # Handle authentication status
# # # # #     if authentication_status:
# # # # #         st.session_state["authentication_status"] = True
# # # # #         st.session_state["name"] = name
# # # # #         st.session_state["username"] = username

# # # # #         # Get user data
# # # # #         user_data = config['credentials']['usernames'][username]
# # # # #         user_role = user_data.get('role', 'viewer')  # Default to 'viewer' if not specified
# # # # #         st.session_state['user_role'] = user_role

# # # # #         # Check for OTP secret
# # # # #         otp_secret = user_data.get('otp_secret', "")

# # # # #         if not otp_secret:
# # # # #             # Generate new OTP secret
# # # # #             otp_secret = pyotp.random_base32()
# # # # #             config['credentials']['usernames'][username]['otp_secret'] = otp_secret
# # # # #             # Save updated config back to Blob Storage
# # # # #             blob_client.upload_blob(yaml.dump(config), overwrite=True)
# # # # #             st.session_state['otp_setup_complete'] = False
# # # # #             st.session_state['show_qr_code'] = True
# # # # #             logging.info("Generated new OTP secret for user %s", username)
# # # # #         else:
# # # # #             st.session_state['otp_setup_complete'] = True

# # # # #         # Initialize TOTP
# # # # #         totp = pyotp.TOTP(otp_secret)
# # # # #         logging.info("Using OTP secret for user %s", username)

# # # # #         # Handle OTP verification
# # # # #         if not st.session_state.get('otp_verified', False):
# # # # #             if st.session_state.get('show_qr_code', False):
# # # # #                 st.title("Welcome! 👋")
# # # # #                 otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoGPT")
# # # # #                 qr = qrcode.make(otp_uri)
# # # # #                 qr = qr.resize((200, 200))
# # # # #                 st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: Google Authenticator)")

# # # # #             st.title("Welcome to SynoptekGPT!")
# # # # #             otp_input = st.text_input("Enter the OTP from your authenticator app", type="password", key='otp_input')
# # # # #             verify_button_clicked = st.button("Verify OTP", key='verify_otp_button')

# # # # #             if verify_button_clicked:
# # # # #                 if totp.verify(otp_input):
# # # # #                     st.session_state['otp_verified'] = True
# # # # #                     st.session_state['show_qr_code'] = False
# # # # #                     st.success(f'Welcome *{name}*')
# # # # #                     logging.info("User %s authenticated successfully with 2FA", username)
# # # # #                     # Proceed to the main app
# # # # #                     return True
# # # # #                 else:
# # # # #                     st.error("Invalid OTP. Please try again.")
# # # # #                     logging.warning("Invalid OTP attempt for user %s", username)
# # # # #                     return False
# # # # #         else:
# # # # #             # User is already verified
# # # # #             st.success(f'Welcome back *{name}*')
# # # # #             logging.info("User %s re-authenticated successfully", username)
# # # # #             return True

# # # # #     elif authentication_status == False:
# # # # #         st.write("# Welcome! 👋")
# # # # #         st.markdown("Please enter your username and password to log in.")
# # # # #         logging.warning("Failed login attempt with username: %s", username)
# # # # #         return False

# # # # #     elif authentication_status == None:
# # # # #         st.write("# Welcome! 👋")
# # # # #         st.markdown("Please enter your username and password to log in.")
# # # # #         return False

# # # # # # Sidebar code
# # # # # with st.sidebar:
# # # # #     st.image(r"./synoptek.png", width=275)
# # # # #     # Authentication widget
# # # # #     name, authentication_status, username = authenticator.login('Login', 'sidebar')

# # # # #     # Logout button (always available after username/password authentication)
# # # # #     if authentication_status:
# # # # #         if st.button("Logout", key='logout_button'):
# # # # #             authenticator.logout('Logout', 'sidebar')
# # # # #             for key in list(st.session_state.keys()):
# # # # #                 del st.session_state[key]
# # # # #             st.rerun()

# # # # #     if authentication_status and st.session_state.get('otp_verified', False):
# # # # #         # Display conversations in the sidebar after full authentication
# # # # #         st.title("Conversations")

# # # # #         # Add "New Chat" button at the top with a unique key
# # # # #         if st.button("New Chat", key='new_chat_button'):
# # # # #             st.session_state.messages = []
# # # # #             st.rerun()

# # # # #         # Functions to load and display conversations
# # # # #         def load_conversations():
# # # # #             try:
# # # # #                 if os.path.exists("conversations.json"):
# # # # #                     with open("conversations.json", "r") as f:
# # # # #                         return json.load(f)
# # # # #                 else:
# # # # #                     return []
# # # # #             except Exception as e:
# # # # #                 st.error("Failed to load conversations.")
# # # # #                 logging.error(f"Load Conversations Error: {e}")
# # # # #                 return []

# # # # #         def get_conversation_title(conversation):
# # # # #             for msg in conversation["messages"]:
# # # # #                 if msg["role"] == "user":
# # # # #                     title = msg["content"].strip()
# # # # #                     # Truncate title if it's too long
# # # # #                     return title[:28] + "..." if len(title) > 28 else title
# # # # #             return "Untitled Conversation"

# # # # #         conversations = load_conversations()

# # # # #         # Categorize conversations
# # # # #         today = []
# # # # #         yesterday = []
# # # # #         previous_7_days = []
# # # # #         previous_30_days = []

# # # # #         now = datetime.datetime.now()
# # # # #         for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # # #             try:
# # # # #                 timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # # #                 delta = now - timestamp
# # # # #                 if delta.days == 0:
# # # # #                     today.append((idx, convo))
# # # # #                 elif delta.days == 1:
# # # # #                     yesterday.append((idx, convo))
# # # # #                 elif delta.days <= 7:
# # # # #                     previous_7_days.append((idx, convo))
# # # # #                 elif delta.days <= 30:
# # # # #                     previous_30_days.append((idx, convo))
# # # # #             except Exception as e:
# # # # #                 logging.error(f"Error processing conversation timestamp: {e}")

# # # # #         # Display categories
# # # # #         if today:
# # # # #             st.subheader("Today")
# # # # #             for idx, convo in today:
# # # # #                 title = get_conversation_title(convo)
# # # # #                 if st.button(title, key=f"today_{idx}"):
# # # # #                     st.session_state.messages = convo["messages"]
# # # # #                     st.rerun()

# # # # #         if yesterday:
# # # # #             st.subheader("Yesterday")
# # # # #             for idx, convo in yesterday:
# # # # #                 title = get_conversation_title(convo)
# # # # #                 if st.button(title, key=f"yesterday_{idx}"):
# # # # #                     st.session_state.messages = convo["messages"]
# # # # #                     st.rerun()

# # # # #         if previous_7_days:
# # # # #             st.subheader("Previous 7 Days")
# # # # #             for idx, convo in previous_7_days:
# # # # #                 title = get_conversation_title(convo)
# # # # #                 if st.button(title, key=f"week_{idx}"):
# # # # #                     st.session_state.messages = convo["messages"]
# # # # #                     st.rerun()

# # # # #         if previous_30_days:
# # # # #             st.subheader("Previous 30 Days")
# # # # #             for idx, convo in previous_30_days:
# # # # #                 title = get_conversation_title(convo)
# # # # #                 if st.button(title, key=f"month_{idx}"):
# # # # #                     st.session_state.messages = convo["messages"]
# # # # #                     st.rerun()

# # # # #     # Add vertical space to push the welcome message and logout button to the bottom
# # # # #     st.markdown("<br><br><br><br><br><br>", unsafe_allow_html=True)

# # # # #     # Welcome message at the bottom (after full authentication)
# # # # #     if authentication_status and st.session_state.get('otp_verified', False):
# # # # #         st.markdown("---")
# # # # #         st.markdown(f'## Hello, *{name}*')

# # # # # # Call the authenticate_user function
# # # # # if authenticate_user(authentication_status, name, username):
# # # # #     # User is authenticated, proceed with the main app code

# # # # #     st.title("Synoptek-GPT! 🤖")

# # # # #     # Initialize session state for messages and model
# # # # #     if "messages" not in st.session_state:
# # # # #         st.session_state.messages = []

# # # # #     if "model" not in st.session_state:
# # # # #         st.session_state.model = "gpt-4o"

# # # # #     # Display previous chat messages
# # # # #     for message in st.session_state["messages"]:
# # # # #         with st.chat_message(message["role"]):
# # # # #             st.markdown(message["content"])

# # # # #     # User input
# # # # #     if user_prompt := st.chat_input("Type here to Chat..."):
# # # # #         st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # # #         with st.chat_message("user"):
# # # # #             st.markdown(user_prompt)

# # # # #         # Function to save a conversation with error handling
# # # # #         def save_conversation(conversation):
# # # # #             try:
# # # # #                 conversations = load_conversations()
# # # # #                 # Append the new conversation with timestamp
# # # # #                 conversations.append({
# # # # #                     "timestamp": datetime.datetime.now().isoformat(),
# # # # #                     "messages": conversation
# # # # #                 })
# # # # #                 # Limit to the most recent 30 conversations
# # # # #                 conversations = conversations[-30:]
# # # # #                 with open("conversations.json", "w") as f:
# # # # #                     json.dump(conversations, f, indent=4)
# # # # #             except Exception as e:
# # # # #                 st.error("Failed to save conversation.")
# # # # #                 logging.error(f"Save Conversation Error: {e}")

# # # # #         # Generate responses with error handling
# # # # #         with st.chat_message("assistant"):
# # # # #             message_placeholder = st.empty()
# # # # #             full_response = ""

# # # # #             try:
# # # # #                 stream = client.chat.completions.create(
# # # # #                     model=st.session_state.model,
# # # # #                     messages=st.session_state.messages,
# # # # #                     stream=True,
# # # # #                     max_tokens=4000,
# # # # #                     temperature=0.2,
# # # # #                 )
# # # # #                 for chunk in stream:
# # # # #                     # Access choices as an attribute
# # # # #                     choices = getattr(chunk, 'choices', None)
# # # # #                     if choices:
# # # # #                         # Access the first choice
# # # # #                         choice = choices[0]
# # # # #                         # Access delta as an attribute
# # # # #                         delta = getattr(choice, 'delta', None)
# # # # #                         if delta:
# # # # #                             # Get content from delta
# # # # #                             token = getattr(delta, 'content', '')
# # # # #                             if token:
# # # # #                                 full_response += token
# # # # #                                 message_placeholder.markdown(full_response + "▌")
# # # # #                 message_placeholder.markdown(full_response)
# # # # #             except Exception as e:
# # # # #                 st.error("An error occurred while generating the response.")
# # # # #                 logging.error(f"API Error: {e}")
# # # # #                 full_response = "I'm sorry, but I'm unable to process your request at the moment."

# # # # #         st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # # #         # Save the conversation after each assistant response
# # # # #         save_conversation(st.session_state.messages)

# # # # # else:
# # # # #     # Stop the app if not authenticated
# # # # #     st.stop()


# # # # import os
# # # # import json
# # # # import datetime
# # # # import logging  # For logging
# # # # import streamlit as st
# # # # from openai import AzureOpenAI
# # # # from dotenv import load_dotenv
# # # # import streamlit_authenticator as stauth
# # # # import pyotp
# # # # import qrcode
# # # # import io
# # # # from io import BytesIO
# # # # from azure.storage.blob import BlobServiceClient
# # # # from yaml.loader import SafeLoader
# # # # import yaml

# # # # # Load environment variables
# # # # load_dotenv()

# # # # # Set up logging to display on the command line
# # # # logging.basicConfig(
# # # #     level=logging.ERROR,
# # # #     format='%(asctime)s %(levelname)s %(message)s'
# # # # )

# # # # # Azure OpenAI configuration
# # # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # # st.set_page_config(
# # # #     page_title="SynoptekGPT",
# # # #     page_icon="🤖",
# # # #     layout="wide",
# # # #     initial_sidebar_state="auto"
# # # # )

# # # # # Initialize the Azure OpenAI client with error handling
# # # # try:
# # # #     client = AzureOpenAI(
# # # #         api_key=azure_openai_api_key,
# # # #         azure_endpoint=azure_endpoint,
# # # #         api_version="2024-04-01-preview",
# # # #     )
# # # # except Exception as e:
# # # #     st.error("Failed to initialize Azure OpenAI client.")
# # # #     logging.error(f"OpenAI Client Initialization Error: {e}")
# # # #     st.stop()

# # # # # Load config from Azure Blob Storage
# # # # connection_string = os.getenv("BLOB_CONNECTION_STRING")
# # # # container_name = "itgluecopilot"
# # # # config_blob_name = "config/config_quad.yaml"

# # # # # BlobServiceClient
# # # # blob_service_client = BlobServiceClient.from_connection_string(connection_string)
# # # # container_client = blob_service_client.get_container_client(container_name)

# # # # # Load the YAML configuration file
# # # # blob_client = container_client.get_blob_client(config_blob_name)
# # # # blob_data = blob_client.download_blob().readall()
# # # # config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# # # # # Initialize the authenticator
# # # # authenticator = stauth.Authenticate(
# # # #     config['credentials'],
# # # #     config['cookie']['name'],
# # # #     config['cookie']['key'],
# # # #     config['cookie']['expiry_days'],
# # # # )

# # # # # Function to handle user authentication
# # # # def authenticate_user(authentication_status, name, username):
# # # #     # Handle authentication status
# # # #     if authentication_status:
# # # #         st.session_state["authentication_status"] = True
# # # #         st.session_state["name"] = name
# # # #         st.session_state["username"] = username

# # # #         # Get user data
# # # #         user_data = config['credentials']['usernames'][username]
# # # #         user_role = user_data.get('role', 'viewer')  # Default to 'viewer' if not specified
# # # #         st.session_state['user_role'] = user_role

# # # #         # Check for OTP secret
# # # #         otp_secret = user_data.get('otp_secret', "")

# # # #         if not otp_secret:
# # # #             # Generate new OTP secret
# # # #             otp_secret = pyotp.random_base32()
# # # #             config['credentials']['usernames'][username]['otp_secret'] = otp_secret
# # # #             # Save updated config back to Blob Storage
# # # #             blob_client.upload_blob(yaml.dump(config), overwrite=True)
# # # #             st.session_state['otp_setup_complete'] = False
# # # #             st.session_state['show_qr_code'] = True
# # # #             logging.info("Generated new OTP secret for user %s", username)
# # # #         else:
# # # #             st.session_state['otp_setup_complete'] = True

# # # #         # Initialize TOTP
# # # #         totp = pyotp.TOTP(otp_secret)
# # # #         logging.info("Using OTP secret for user %s", username)

# # # #         # Handle OTP verification
# # # #         if not st.session_state.get('otp_verified', False):
# # # #             if st.session_state.get('show_qr_code', False):
# # # #                 st.title("Welcome! 👋")
# # # #                 otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoptekGPT")
# # # #                 qr = qrcode.make(otp_uri)
# # # #                 qr = qr.resize((200, 200))
# # # #                 st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: Google Authenticator)")

# # # #             st.title("Welcome to SynoptekGPT!")
# # # #             otp_input = st.text_input("Enter the OTP from your authenticator app", type="password", key='otp_input')
# # # #             verify_button_clicked = st.button("Verify OTP", key='verify_otp_button')

# # # #             if verify_button_clicked:
# # # #                 if totp.verify(otp_input):
# # # #                     st.session_state['otp_verified'] = True
# # # #                     st.session_state['show_qr_code'] = False
# # # #                     st.success(f'Welcome *{name}*')
# # # #                     logging.info("User %s authenticated successfully with 2FA", username)
# # # #                     # Proceed to the main app
# # # #                     return True
# # # #                 else:
# # # #                     st.error("Invalid OTP. Please try again.")
# # # #                     logging.warning("Invalid OTP attempt for user %s", username)
# # # #                     return False
# # # #         else:
# # # #             # User is already verified
# # # #             st.success(f'Welcome back *{name}*')
# # # #             logging.info("User %s re-authenticated successfully", username)
# # # #             return True

# # # #     elif authentication_status == False:
# # # #         st.write("# Welcome! 👋")
# # # #         st.markdown("Please enter your username and password to log in.")
# # # #         logging.warning("Failed login attempt with username: %s", username)
# # # #         return False

# # # #     elif authentication_status == None:
# # # #         st.write("# Welcome! 👋")
# # # #         st.markdown("Please enter your username and password to log in.")
# # # #         return False

# # # # # Sidebar code
# # # # with st.sidebar:
# # # #     st.image(r"./synoptek.png", width=275)
# # # #     # Authentication widget
# # # #     name, authentication_status, username = authenticator.login('Login', 'sidebar')

# # # #     if authentication_status and st.session_state.get('otp_verified', False):
# # # #         # Display conversations in the sidebar after full authentication
# # # #         st.title("Conversations")

# # # #         # Add "New Chat" button at the top with a unique key
# # # #         if st.button("New Chat", key='new_chat_button'):
# # # #             st.session_state.messages = []
# # # #             st.rerun()

# # # #         # Functions to load and display conversations
# # # #         def load_conversations():
# # # #             try:
# # # #                 if os.path.exists("conversations.json"):
# # # #                     with open("conversations.json", "r") as f:
# # # #                         return json.load(f)
# # # #                 else:
# # # #                     return []
# # # #             except Exception as e:
# # # #                 st.error("Failed to load conversations.")
# # # #                 logging.error(f"Load Conversations Error: {e}")
# # # #                 return []

# # # #         def get_conversation_title(conversation):
# # # #             for msg in conversation["messages"]:
# # # #                 if msg["role"] == "user":
# # # #                     title = msg["content"].strip()
# # # #                     # Truncate title if it's too long
# # # #                     return title[:28] + "..." if len(title) > 28 else title
# # # #             return "Untitled Conversation"

# # # #         conversations = load_conversations()

# # # #         # Categorize conversations
# # # #         today = []
# # # #         yesterday = []
# # # #         previous_7_days = []
# # # #         previous_30_days = []

# # # #         now = datetime.datetime.now()
# # # #         for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # # #             try:
# # # #                 timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # # #                 delta = now - timestamp
# # # #                 if delta.days == 0:
# # # #                     today.append((idx, convo))
# # # #                 elif delta.days == 1:
# # # #                     yesterday.append((idx, convo))
# # # #                 elif delta.days <= 7:
# # # #                     previous_7_days.append((idx, convo))
# # # #                 elif delta.days <= 30:
# # # #                     previous_30_days.append((idx, convo))
# # # #             except Exception as e:
# # # #                 logging.error(f"Error processing conversation timestamp: {e}")

# # # #         # Display categories
# # # #         if today:
# # # #             st.subheader("Today")
# # # #             for idx, convo in today:
# # # #                 title = get_conversation_title(convo)
# # # #                 if st.button(title, key=f"today_{idx}"):
# # # #                     st.session_state.messages = convo["messages"]
# # # #                     st.rerun()

# # # #         if yesterday:
# # # #             st.subheader("Yesterday")
# # # #             for idx, convo in yesterday:
# # # #                 title = get_conversation_title(convo)
# # # #                 if st.button(title, key=f"yesterday_{idx}"):
# # # #                     st.session_state.messages = convo["messages"]
# # # #                     st.rerun()

# # # #         if previous_7_days:
# # # #             st.subheader("Previous 7 Days")
# # # #             for idx, convo in previous_7_days:
# # # #                 title = get_conversation_title(convo)
# # # #                 if st.button(title, key=f"week_{idx}"):
# # # #                     st.session_state.messages = convo["messages"]
# # # #                     st.rerun()

# # # #         if previous_30_days:
# # # #             st.subheader("Previous 30 Days")
# # # #             for idx, convo in previous_30_days:
# # # #                 title = get_conversation_title(convo)
# # # #                 if st.button(title, key=f"month_{idx}"):
# # # #                     st.session_state.messages = convo["messages"]
# # # #                     st.rerun()

# # # #     # Add vertical space to push the welcome message and logout button to the bottom
# # # #     st.markdown("<br><br><br><br><br><br><br><br><br>", unsafe_allow_html=True)
# # # #     st.markdown("---")

# # # #     if authentication_status:
# # # #         # Welcome message and logout button at the bottom
# # # #         st.markdown(f'## Hello, *{name}*')
# # # #         if st.button("Logout", key='logout_button'):
# # # #             authenticator.logout('Logout', 'sidebar')
# # # #             for key in list(st.session_state.keys()):
# # # #                 del st.session_state[key]
# # # #             st.rerun()
# # # #     elif authentication_status == False:
# # # #         st.error('Username/password is incorrect')
# # # #     elif authentication_status == None:
# # # #         st.warning('Please enter your username and password')

# # # # # Call the authenticate_user function
# # # # if authenticate_user(authentication_status, name, username):
# # # #     # User is authenticated, proceed with the main app code

# # # #     st.title("Synoptek-GPT! 🤖")

# # # #     # Initialize session state for messages and model
# # # #     if "messages" not in st.session_state:
# # # #         st.session_state.messages = []

# # # #     if "model" not in st.session_state:
# # # #         st.session_state.model = "gpt-4o"

# # # #     # Display previous chat messages
# # # #     for message in st.session_state["messages"]:
# # # #         with st.chat_message(message["role"]):
# # # #             st.markdown(message["content"])

# # # #     # User input
# # # #     if user_prompt := st.chat_input("Type here to Chat..."):
# # # #         st.session_state.messages.append({"role": "user", "content": user_prompt})
# # # #         with st.chat_message("user"):
# # # #             st.markdown(user_prompt)

# # # #         # Function to save a conversation with error handling
# # # #         def save_conversation(conversation):
# # # #             try:
# # # #                 conversations = load_conversations()
# # # #                 # Append the new conversation with timestamp
# # # #                 conversations.append({
# # # #                     "timestamp": datetime.datetime.now().isoformat(),
# # # #                     "messages": conversation
# # # #                 })
# # # #                 # Limit to the most recent 30 conversations
# # # #                 conversations = conversations[-30:]
# # # #                 with open("conversations.json", "w") as f:
# # # #                     json.dump(conversations, f, indent=4)
# # # #             except Exception as e:
# # # #                 st.error("Failed to save conversation.")
# # # #                 logging.error(f"Save Conversation Error: {e}")

# # # #         # Generate responses with error handling
# # # #         with st.chat_message("assistant"):
# # # #             message_placeholder = st.empty()
# # # #             full_response = ""

# # # #             try:
# # # #                 stream = client.chat.completions.create(
# # # #                     model=st.session_state.model,
# # # #                     messages=st.session_state.messages,
# # # #                     stream=True,
# # # #                     max_tokens=4000,
# # # #                     temperature=0.2,
# # # #                 )
# # # #                 for chunk in stream:
# # # #                     # Access choices as an attribute
# # # #                     choices = getattr(chunk, 'choices', None)
# # # #                     if choices:
# # # #                         # Access the first choice
# # # #                         choice = choices[0]
# # # #                         # Access delta as an attribute
# # # #                         delta = getattr(choice, 'delta', None)
# # # #                         if delta:
# # # #                             # Get content from delta
# # # #                             token = getattr(delta, 'content', '')
# # # #                             if token:
# # # #                                 full_response += token
# # # #                                 message_placeholder.markdown(full_response + "▌")
# # # #                 message_placeholder.markdown(full_response)
# # # #             except Exception as e:
# # # #                 st.error("An error occurred while generating the response.")
# # # #                 logging.error(f"API Error: {e}")
# # # #                 full_response = "I'm sorry, but I'm unable to process your request at the moment."

# # # #         st.session_state.messages.append({"role": "assistant", "content": full_response})

# # # #         # Save the conversation after each assistant response
# # # #         save_conversation(st.session_state.messages)

# # # # else:
# # # #     # Stop the app if not authenticated
# # # #     st.stop()


# # # import os
# # # import json
# # # import datetime
# # # import logging  # For logging
# # # import streamlit as st
# # # from openai import AzureOpenAI
# # # from dotenv import load_dotenv
# # # import streamlit_authenticator as stauth
# # # import pyotp
# # # import qrcode
# # # import io
# # # from io import BytesIO
# # # from azure.storage.blob import BlobServiceClient
# # # from yaml.loader import SafeLoader
# # # import yaml

# # # # Load environment variables
# # # load_dotenv()

# # # # Set up logging to display on the command line
# # # logging.basicConfig(
# # #     level=logging.ERROR,
# # #     format='%(asctime)s %(levelname)s %(message)s'
# # # )

# # # # Azure OpenAI configuration
# # # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # # st.set_page_config(
# # #     page_title="SynoptekGPT",
# # #     page_icon="🤖",
# # #     layout="wide",
# # #     initial_sidebar_state="auto"
# # # )

# # # # Initialize the Azure OpenAI client with error handling
# # # try:
# # #     client = AzureOpenAI(
# # #         api_key=azure_openai_api_key,
# # #         azure_endpoint=azure_endpoint,
# # #         api_version="2024-04-01-preview",
# # #     )
# # # except Exception as e:
# # #     st.error("Failed to initialize Azure OpenAI client.")
# # #     logging.error(f"OpenAI Client Initialization Error: {e}")
# # #     st.stop()

# # # # Load config from Azure Blob Storage
# # # connection_string = os.getenv("BLOB_CONNECTION_STRING")
# # # container_name = "itgluecopilot"
# # # config_blob_name = "config/config_quad.yaml"

# # # # BlobServiceClient
# # # blob_service_client = BlobServiceClient.from_connection_string(connection_string)
# # # container_client = blob_service_client.get_container_client(container_name)

# # # # Load the YAML configuration file
# # # blob_client = container_client.get_blob_client(config_blob_name)
# # # blob_data = blob_client.download_blob().readall()
# # # config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# # # # Initialize the authenticator
# # # authenticator = stauth.Authenticate(
# # #     config['credentials'],
# # #     config['cookie']['name'],
# # #     config['cookie']['key'],
# # #     config['cookie']['expiry_days'],
# # # )

# # # # Function to handle user authentication
# # # def authenticate_user(authentication_status, name, username):
# # #     # Handle authentication status
# # #     if authentication_status:
# # #         st.session_state["authentication_status"] = True
# # #         st.session_state["name"] = name
# # #         st.session_state["username"] = username

# # #         # Get user data
# # #         user_data = config['credentials']['usernames'][username]
# # #         user_role = user_data.get('role', 'viewer')  # Default to 'viewer' if not specified
# # #         st.session_state['user_role'] = user_role

# # #         # Check for OTP secret
# # #         otp_secret = user_data.get('otp_secret', "")

# # #         if not otp_secret:
# # #             # Generate new OTP secret
# # #             otp_secret = pyotp.random_base32()
# # #             config['credentials']['usernames'][username]['otp_secret'] = otp_secret
# # #             # Save updated config back to Blob Storage
# # #             blob_client.upload_blob(yaml.dump(config), overwrite=True)
# # #             st.session_state['otp_setup_complete'] = False
# # #             st.session_state['show_qr_code'] = True
# # #             logging.info("Generated new OTP secret for user %s", username)
# # #         else:
# # #             st.session_state['otp_setup_complete'] = True

# # #         # Initialize TOTP
# # #         totp = pyotp.TOTP(otp_secret)
# # #         logging.info("Using OTP secret for user %s", username)

# # #         # Handle OTP verification
# # #         if not st.session_state.get('otp_verified', False):
# # #             if st.session_state.get('show_qr_code', False):
# # #                 st.title("Welcome! 👋")
# # #                 otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoGPT")
# # #                 qr = qrcode.make(otp_uri)
# # #                 qr = qr.resize((200, 200))
# # #                 st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: Google Authenticator)")

# # #             st.title("Welcome to SynoptekGPT!")
# # #             otp_input = st.text_input("Enter the OTP from your authenticator app", type="password", key='otp_input')
# # #             verify_button_clicked = st.button("Verify OTP", key='verify_otp_button')

# # #             if verify_button_clicked:
# # #                 if totp.verify(otp_input):
# # #                     st.session_state['otp_verified'] = True
# # #                     st.session_state['show_qr_code'] = False
# # #                     st.success(f'Welcome *{name}*')
# # #                     logging.info("User %s authenticated successfully with 2FA", username)
# # #                     # Proceed to the main app
# # #                     return True
# # #                 else:
# # #                     st.error("Invalid OTP. Please try again.")
# # #                     logging.warning("Invalid OTP attempt for user %s", username)
# # #                     return False
# # #         else:
# # #             # User is already verified
# # #             st.success(f'Welcome back *{name}*')
# # #             logging.info("User %s re-authenticated successfully", username)
# # #             return True

# # #     elif authentication_status == False:
# # #         st.write("# Welcome! 👋")
# # #         st.markdown("Please enter your username and password to log in.")
# # #         logging.warning("Failed login attempt with username: %s", username)
# # #         return False

# # #     elif authentication_status == None:
# # #         st.write("# Welcome! 👋")
# # #         st.markdown("Please enter your username and password to log in.")
# # #         return False

# # # # Sidebar code
# # # with st.sidebar:
# # #     st.image(r"./synoptek.png", width=275)
# # #     # Authentication widget
# # #     name, authentication_status, username = authenticator.login('Login', 'sidebar')

# # #     if authentication_status and st.session_state.get('otp_verified', False):
# # #         # Display conversations in the sidebar after full authentication
# # #         st.title("Conversations")

# # #         # Add "New Chat" button at the top with a unique key
# # #         if st.button("New Chat", key='new_chat_button'):
# # #             st.session_state.messages = []
# # #             st.rerun()

# # #         # Functions to load and display conversations
# # #         def load_conversations():
# # #             try:
# # #                 if os.path.exists("conversations.json"):
# # #                     with open("conversations.json", "r") as f:
# # #                         return json.load(f)
# # #                 else:
# # #                     return []
# # #             except Exception as e:
# # #                 st.error("Failed to load conversations.")
# # #                 logging.error(f"Load Conversations Error: {e}")
# # #                 return []

# # #         def get_conversation_title(conversation):
# # #             for msg in conversation["messages"]:
# # #                 if msg["role"] == "user":
# # #                     title = msg["content"].strip()
# # #                     # Truncate title if it's too long
# # #                     return title[:28] + "..." if len(title) > 28 else title
# # #             return "Untitled Conversation"

# # #         conversations = load_conversations()

# # #         # Categorize conversations
# # #         today = []
# # #         yesterday = []
# # #         previous_7_days = []
# # #         previous_30_days = []

# # #         now = datetime.datetime.now()
# # #         for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# # #             try:
# # #                 timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# # #                 delta = now - timestamp
# # #                 if delta.days == 0:
# # #                     today.append((idx, convo))
# # #                 elif delta.days == 1:
# # #                     yesterday.append((idx, convo))
# # #                 elif delta.days <= 7:
# # #                     previous_7_days.append((idx, convo))
# # #                 elif delta.days <= 30:
# # #                     previous_30_days.append((idx, convo))
# # #             except Exception as e:
# # #                 logging.error(f"Error processing conversation timestamp: {e}")

# # #         # Display categories
# # #         if today:
# # #             st.subheader("Today")
# # #             for idx, convo in today:
# # #                 title = get_conversation_title(convo)
# # #                 if st.button(title, key=f"today_{idx}"):
# # #                     st.session_state.messages = convo["messages"]
# # #                     st.rerun()

# # #         if yesterday:
# # #             st.subheader("Yesterday")
# # #             for idx, convo in yesterday:
# # #                 title = get_conversation_title(convo)
# # #                 if st.button(title, key=f"yesterday_{idx}"):
# # #                     st.session_state.messages = convo["messages"]
# # #                     st.rerun()

# # #         if previous_7_days:
# # #             st.subheader("Previous 7 Days")
# # #             for idx, convo in previous_7_days:
# # #                 title = get_conversation_title(convo)
# # #                 if st.button(title, key=f"week_{idx}"):
# # #                     st.session_state.messages = convo["messages"]
# # #                     st.rerun()

# # #         if previous_30_days:
# # #             st.subheader("Previous 30 Days")
# # #             for idx, convo in previous_30_days:
# # #                 title = get_conversation_title(convo)
# # #                 if st.button(title, key=f"month_{idx}"):
# # #                     st.session_state.messages = convo["messages"]
# # #                     st.rerun()

# # #     # Add vertical space to push the welcome message and logout button to the bottom
# # #     st.markdown("<br><br><br><br><br><br>", unsafe_allow_html=True)
# # #     st.markdown("---")

# # #     if authentication_status:
# # #         # Welcome message and logout button at the bottom
# # #         st.markdown(f'## Hello, *{name}*')
# # #         if st.button("Logout", key='logout_button'):
# # #             authenticator.logout('Logout', 'sidebar')
# # #             for key in list(st.session_state.keys()):
# # #                 del st.session_state[key]
# # #             st.rerun()
# # #     elif authentication_status == False:
# # #         st.error('Username/password is incorrect')
# # #     elif authentication_status == None:
# # #         st.warning('Please enter your username and password')

# # # # Call the authenticate_user function
# # # if authenticate_user(authentication_status, name, username):
# # #     # User is authenticated, proceed with the main app code

# # #     st.title("Synoptek-GPT! 🤖")

# # #     # Initialize session state for messages and model
# # #     if "messages" not in st.session_state:
# # #         st.session_state.messages = []

# # #     if "model" not in st.session_state:
# # #         st.session_state.model = "gpt-4o"

# # #     # If there are no messages yet, display the image or text
# # #     if not st.session_state.messages:
# # #         # Display an image or text until the user types
# # #         st.image(r"D:\Project\Quad-C\chatbot.png", width=375)
# # #         st.write("Welcome to SynoptekGPT! Here you will be able to try out multiple models.")
    
# # #     # Display previous chat messages
# # #     else:
# # #         for message in st.session_state["messages"]:
# # #             with st.chat_message(message["role"]):
# # #                 st.markdown(message["content"])

# # #     # User input
# # #     if user_prompt := st.chat_input("Type here to Chat..."):
# # #         st.session_state.messages.append({"role": "user", "content": user_prompt})
# # #         with st.chat_message("user"):
# # #             st.markdown(user_prompt)

# # #         # Function to save a conversation with error handling
# # #         def save_conversation(conversation):
# # #             try:
# # #                 conversations = load_conversations()
# # #                 # Append the new conversation with timestamp
# # #                 conversations.append({
# # #                     "timestamp": datetime.datetime.now().isoformat(),
# # #                     "messages": conversation
# # #                 })
# # #                 # Limit to the most recent 30 conversations
# # #                 conversations = conversations[-30:]
# # #                 with open("conversations.json", "w") as f:
# # #                     json.dump(conversations, f, indent=4)
# # #             except Exception as e:
# # #                 st.error("Failed to save conversation.")
# # #                 logging.error(f"Save Conversation Error: {e}")

# # #         # Generate responses with error handling
# # #         with st.chat_message("assistant"):
# # #             message_placeholder = st.empty()
# # #             full_response = ""

# # #             try:
# # #                 stream = client.chat.completions.create(
# # #                     model=st.session_state.model,
# # #                     messages=st.session_state.messages,
# # #                     stream=True,
# # #                     max_tokens=4000,
# # #                     temperature=0.2,
# # #                 )
# # #                 for chunk in stream:
# # #                     # Access choices as an attribute
# # #                     choices = getattr(chunk, 'choices', None)
# # #                     if choices:
# # #                         # Access the first choice
# # #                         choice = choices[0]
# # #                         # Access delta as an attribute
# # #                         delta = getattr(choice, 'delta', None)
# # #                         if delta:
# # #                             # Get content from delta
# # #                             token = getattr(delta, 'content', '')
# # #                             if token:
# # #                                 full_response += token
# # #                                 message_placeholder.markdown(full_response + "▌")
# # #                 message_placeholder.markdown(full_response)
# # #             except Exception as e:
# # #                 st.error("An error occurred while generating the response.")
# # #                 logging.error(f"API Error: {e}")
# # #                 full_response = "I'm sorry, but I'm unable to process your request at the moment."

# # #         st.session_state.messages.append({"role": "assistant", "content": full_response})

# # #         # Save the conversation after each assistant response
# # #         save_conversation(st.session_state.messages)

# # # else:
# # #     # Stop the app if not authenticated
# # #     st.stop()



# # import os
# # import json
# # import datetime
# # import logging  # For logging
# # import streamlit as st
# # from openai import AzureOpenAI
# # from dotenv import load_dotenv
# # import streamlit_authenticator as stauth
# # import pyotp
# # import qrcode
# # import io
# # from io import BytesIO
# # from azure.storage.blob import BlobServiceClient
# # from yaml.loader import SafeLoader
# # import yaml

# # # Load environment variables
# # load_dotenv()

# # # Set up logging to display on the command line
# # logging.basicConfig(
# #     level=logging.ERROR,
# #     format='%(asctime)s %(levelname)s %(message)s'
# # )

# # # Azure OpenAI configuration
# # azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# # azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# # st.set_page_config(
# #     page_title="SynoptekGPT",
# #     page_icon="🤖",
# #     layout="wide",
# #     initial_sidebar_state="auto"
# # )

# # # Initialize the Azure OpenAI client with error handling
# # try:
# #     client = AzureOpenAI(
# #         api_key=azure_openai_api_key,
# #         azure_endpoint=azure_endpoint,
# #         api_version="2024-04-01-preview",
# #     )
# # except Exception as e:
# #     st.error("Failed to initialize Azure OpenAI client.")
# #     logging.error(f"OpenAI Client Initialization Error: {e}")
# #     st.stop()

# # # Load config from Azure Blob Storage
# # connection_string = os.getenv("BLOB_CONNECTION_STRING")
# # container_name = "itgluecopilot"
# # config_blob_name = "config/config_quad.yaml"

# # # BlobServiceClient
# # blob_service_client = BlobServiceClient.from_connection_string(connection_string)
# # container_client = blob_service_client.get_container_client(container_name)

# # # Load the YAML configuration file
# # blob_client = container_client.get_blob_client(config_blob_name)
# # blob_data = blob_client.download_blob().readall()
# # config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# # # Initialize the authenticator
# # authenticator = stauth.Authenticate(
# #     config['credentials'],
# #     config['cookie']['name'],
# #     config['cookie']['key'],
# #     config['cookie']['expiry_days'],
# # )

# # # Function to handle user authentication
# # def authenticate_user(authentication_status, name, username):
# #     # Handle authentication status
# #     if authentication_status:
# #         st.session_state["authentication_status"] = True
# #         st.session_state["name"] = name
# #         st.session_state["username"] = username

# #         # Get user data
# #         user_data = config['credentials']['usernames'][username]
# #         user_role = user_data.get('role', 'viewer')  # Default to 'viewer' if not specified
# #         st.session_state['user_role'] = user_role

# #         # Check for OTP secret
# #         otp_secret = user_data.get('otp_secret', "")

# #         if not otp_secret:
# #             # Generate new OTP secret
# #             otp_secret = pyotp.random_base32()
# #             config['credentials']['usernames'][username]['otp_secret'] = otp_secret
# #             # Save updated config back to Blob Storage
# #             blob_client.upload_blob(yaml.dump(config), overwrite=True)
# #             st.session_state['otp_setup_complete'] = False
# #             st.session_state['show_qr_code'] = True
# #             logging.info("Generated new OTP secret for user %s", username)
# #         else:
# #             st.session_state['otp_setup_complete'] = True

# #         # Initialize TOTP
# #         totp = pyotp.TOTP(otp_secret)
# #         logging.info("Using OTP secret for user %s", username)

# #         # Handle OTP verification
# #         if not st.session_state.get('otp_verified', False):
# #             if st.session_state.get('show_qr_code', False):
# #                 st.title("Welcome! 👋")
# #                 otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoGPT")
# #                 qr = qrcode.make(otp_uri)
# #                 qr = qr.resize((200, 200))
# #                 st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: Google Authenticator)")

# #             st.title("Welcome to SynoptekGPT!")
# #             otp_input = st.text_input("Enter the OTP from your authenticator app", type="password", key='otp_input')
# #             verify_button_clicked = st.button("Verify OTP", key='verify_otp_button')

# #             if verify_button_clicked:
# #                 if totp.verify(otp_input):
# #                     st.session_state['otp_verified'] = True
# #                     st.session_state['show_qr_code'] = False
# #                     st.success(f'Welcome *{name}*')
# #                     logging.info("User %s authenticated successfully with 2FA", username)
# #                     # Proceed to the main app
# #                     return True
# #                 else:
# #                     st.error("Invalid OTP. Please try again.")
# #                     logging.warning("Invalid OTP attempt for user %s", username)
# #                     return False
# #         else:
# #             # User is already verified
# #             st.success(f'Welcome back *{name}*')
# #             logging.info("User %s re-authenticated successfully", username)
# #             return True

# #     elif authentication_status == False:
# #         st.write("# Welcome! 👋")
# #         st.markdown("Please enter your username and password to log in.")
# #         logging.warning("Failed login attempt with username: %s", username)
# #         return False

# #     elif authentication_status == None:
# #         st.write("# Welcome! 👋")
# #         st.markdown("Please enter your username and password to log in.")
# #         return False

# # # Sidebar code
# # with st.sidebar:
# #     st.image(r"./synoptek.png", width=275)
# #     # Authentication widget
# #     name, authentication_status, username = authenticator.login('Login', 'sidebar')

# #     if authentication_status and st.session_state.get('otp_verified', False):
# #         # Display conversations in the sidebar after full authentication
# #         st.title("Conversations")

# #         # Add "New Chat" button at the top with a unique key
# #         if st.button("New Chat", key='new_chat_button'):
# #             st.session_state.messages = []
# #             # st.rerun()    

# #         # Functions to load and display conversations
# #         def load_conversations():
# #             try:
# #                 if os.path.exists("conversations.json"):
# #                     with open("conversations.json", "r") as f:
# #                         return json.load(f)
# #                 else:
# #                     return []
# #             except Exception as e:
# #                 st.error("Failed to load conversations.")
# #                 logging.error(f"Load Conversations Error: {e}")
# #                 return []

# #         def get_conversation_title(conversation):
# #             for msg in conversation["messages"]:
# #                 if msg["role"] == "user":
# #                     title = msg["content"].strip()
# #                     # Truncate title if it's too long
# #                     return title[:28] + "..." if len(title) > 28 else title
# #             return "Untitled Conversation"

# #         conversations = load_conversations()

# #         # Categorize conversations
# #         today = []
# #         yesterday = []
# #         previous_7_days = []
# #         previous_30_days = []

# #         now = datetime.datetime.now()
# #         for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
# #             try:
# #                 timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
# #                 delta = now - timestamp
# #                 if delta.days == 0:
# #                     today.append((idx, convo))
# #                 elif delta.days == 1:
# #                     yesterday.append((idx, convo))
# #                 elif delta.days <= 7:
# #                     previous_7_days.append((idx, convo))
# #                 elif delta.days <= 30:
# #                     previous_30_days.append((idx, convo))
# #             except Exception as e:
# #                 logging.error(f"Error processing conversation timestamp: {e}")

# #         # Display categories
# #         if today:
# #             st.subheader("Today")
# #             for idx, convo in today:
# #                 title = get_conversation_title(convo)
# #                 if st.button(title, key=f"today_{idx}"):
# #                     st.session_state.messages = convo["messages"]
# #                     st.rerun()

# #         if yesterday:
# #             st.subheader("Yesterday")
# #             for idx, convo in yesterday:
# #                 title = get_conversation_title(convo)
# #                 if st.button(title, key=f"yesterday_{idx}"):
# #                     st.session_state.messages = convo["messages"]
# #                     st.rerun()

# #         if previous_7_days:
# #             st.subheader("Previous 7 Days")
# #             for idx, convo in previous_7_days:
# #                 title = get_conversation_title(convo)
# #                 if st.button(title, key=f"week_{idx}"):
# #                     st.session_state.messages = convo["messages"]
# #                     st.rerun()

# #         if previous_30_days:
# #             st.subheader("Previous 30 Days")
# #             for idx, convo in previous_30_days:
# #                 title = get_conversation_title(convo)
# #                 if st.button(title, key=f"month_{idx}"):
# #                     st.session_state.messages = convo["messages"]
# #                     st.rerun()

# #     # Add vertical space to push the welcome message and logout button to the bottom
# #     st.markdown("<br><br><br><br><br><br>", unsafe_allow_html=True)
# #     st.markdown("---")

# #     if authentication_status:
# #         # Welcome message and logout button at the bottom
# #         st.markdown(f'## Hello, *{name}*')
# #         if st.button("Logout", key='logout_button'):
# #             authenticator.logout('Logout', 'sidebar')
# #             for key in list(st.session_state.keys()):
# #                 del st.session_state[key]
# #             st.rerun()
# #     elif authentication_status == False:
# #         st.error('Username/password is incorrect')
# #     elif authentication_status == None:
# #         st.warning('Please enter your username and password')

# # # Call the authenticate_user function
# # if authenticate_user(authentication_status, name, username):
# #     # User is authenticated, proceed with the main app code

# #     st.title("Synoptek-GPT! 🤖")

# #     # Initialize session state for messages and model
# #     if "messages" not in st.session_state:
# #         st.session_state.messages = []

# #     if "model" not in st.session_state:
# #         st.session_state.model = "gpt-4o"

# #     # User input
# #     user_prompt = st.chat_input("Type here to Chat...")

# #     if user_prompt:
# #         # Append user's message to session state
# #         st.session_state.messages.append({"role": "user", "content": user_prompt})

# #         # Display previous chat messages (excluding the last message, which is the new user input)
# #         for message in st.session_state.messages[:-1]:
# #             with st.chat_message(message["role"]):
# #                 st.markdown(message["content"])

# #         # Display user's latest message
# #         with st.chat_message("user"):
# #             st.markdown(user_prompt)

# #         # Generate assistant's response and display it as it's being generated
# #         with st.chat_message("assistant"):
# #             message_placeholder = st.empty()
# #             full_response = ""

# #             try:
# #                 stream = client.chat.completions.create(
# #                     model=st.session_state.model,
# #                     messages=st.session_state.messages,
# #                     stream=True,
# #                     max_tokens=4000,
# #                     temperature=0.2,
# #                 )
# #                 for chunk in stream:
# #                     choices = getattr(chunk, 'choices', None)
# #                     if choices:
# #                         choice = choices[0]
# #                         delta = getattr(choice, 'delta', None)
# #                         if delta:
# #                             token = getattr(delta, 'content', '')
# #                             if token:
# #                                 full_response += token
# #                                 message_placeholder.markdown(full_response + "▌")
# #                 message_placeholder.markdown(full_response)
# #             except Exception as e:
# #                 st.error("An error occurred while generating the response.")
# #                 logging.error(f"API Error: {e}")
# #                 full_response = "I'm sorry, but I'm unable to process your request at the moment."
# #                 message_placeholder.markdown(full_response)

# #         # Append assistant's response to session state
# #         st.session_state.messages.append({"role": "assistant", "content": full_response})

# #         # Function to save a conversation with error handling
# #         def save_conversation(conversation):
# #             try:
# #                 conversations = load_conversations()
# #                 # Append the new conversation with timestamp
# #                 conversations.append({
# #                     "timestamp": datetime.datetime.now().isoformat(),
# #                     "messages": conversation
# #                 })
# #                 # Limit to the most recent 30 conversations
# #                 conversations = conversations[-30:]
# #                 with open("conversations.json", "w") as f:
# #                     json.dump(conversations, f, indent=4)
# #             except Exception as e:
# #                 st.error("Failed to save conversation.")
# #                 logging.error(f"Save Conversation Error: {e}")

# #         # Save the conversation after each assistant response
# #         save_conversation(st.session_state.messages)

# #     else:
# #         # If no new user input, display all messages
# #         if st.session_state.messages:
# #             for message in st.session_state.messages:
# #                 with st.chat_message(message["role"]):
# #                     st.markdown(message["content"])
# #         else:
# #             # # Display an image or text until the user types
# #             # st.image(r"D:\Project\Quad-C\chatbot.png", width=375)
# #             # st.write("Welcome to SynoptekGPT! Here you will be able to try out multiple models.")
# #             col1, col2, col3 = st.columns([1, 2, 1])
# #             with col1:
# #                 st.write("")
# #             with col2:
# #                 st.image(r"D:\Project\Quad-C\chatbot.png", width=375)
# #             with col3:
# #                 st.write("")
# #             # Optionally, center the welcome text as well
# #             st.markdown(
# #                 "<h4 style='text-align: center;'>Welcome to SynoptekGPT! Here you will be able to try out multiple models.</h4>",
# #                 unsafe_allow_html=True
# #             )

# # else:
# #     # Stop the app if not authenticated
# #     st.stop()


# import os
# import json
# import datetime
# import logging  # For logging
# import streamlit as st
# from openai import AzureOpenAI
# from dotenv import load_dotenv
# import streamlit_authenticator as stauth
# import pyotp
# import qrcode
# import io
# from io import BytesIO
# from azure.storage.blob import BlobServiceClient
# from yaml.loader import SafeLoader
# import yaml
# import uuid  # Added for generating unique IDs

# # Load environment variables
# load_dotenv()

# # Set up logging to display on the command line
# logging.basicConfig(
#     level=logging.ERROR,
#     format='%(asctime)s %(levelname)s %(message)s'
# )

# # Azure OpenAI configuration
# azure_openai_api_key = os.getenv("OPENAI_API_KEY_AZURE")
# azure_endpoint = os.getenv("OPENAI_ENDPOINT_AZURE")

# st.set_page_config(
#     page_title="SynoptekGPT",
#     page_icon="🤖",
#     layout="wide",
#     initial_sidebar_state="auto"
# )

# # Initialize the Azure OpenAI client with error handling
# try:
#     client = AzureOpenAI(
#         api_key=azure_openai_api_key,
#         azure_endpoint=azure_endpoint,
#         api_version="2024-04-01-preview",
#     )
# except Exception as e:
#     st.error("Failed to initialize Azure OpenAI client.")
#     logging.error(f"OpenAI Client Initialization Error: {e}")
#     st.stop()

# # Load config from Azure Blob Storage
# connection_string = os.getenv("BLOB_CONNECTION_STRING")
# container_name = "itgluecopilot"
# config_blob_name = "config/config_quad.yaml"

# # BlobServiceClient
# blob_service_client = BlobServiceClient.from_connection_string(connection_string)
# container_client = blob_service_client.get_container_client(container_name)

# # Load the YAML configuration file
# blob_client = container_client.get_blob_client(config_blob_name)
# blob_data = blob_client.download_blob().readall()
# config = yaml.load(io.BytesIO(blob_data), Loader=SafeLoader)

# # Initialize the authenticator
# authenticator = stauth.Authenticate(
#     config['credentials'],
#     config['cookie']['name'],
#     config['cookie']['key'],
#     config['cookie']['expiry_days'],
# )

# # Function to handle user authentication
# def authenticate_user(authentication_status, name, username):
#     # Handle authentication status
#     if authentication_status:
#         st.session_state["authentication_status"] = True
#         st.session_state["name"] = name
#         st.session_state["username"] = username

#         # Get user data
#         user_data = config['credentials']['usernames'][username]
#         user_role = user_data.get('role', 'viewer')  # Default to 'viewer' if not specified
#         st.session_state['user_role'] = user_role

#         # Check for OTP secret
#         otp_secret = user_data.get('otp_secret', "")

#         if not otp_secret:
#             # Generate new OTP secret
#             otp_secret = pyotp.random_base32()
#             config['credentials']['usernames'][username]['otp_secret'] = otp_secret
#             # Save updated config back to Blob Storage
#             blob_client.upload_blob(yaml.dump(config), overwrite=True)
#             st.session_state['otp_setup_complete'] = False
#             st.session_state['show_qr_code'] = True
#             logging.info("Generated new OTP secret for user %s", username)
#         else:
#             st.session_state['otp_setup_complete'] = True

#         # Initialize TOTP
#         totp = pyotp.TOTP(otp_secret)
#         logging.info("Using OTP secret for user %s", username)

#         # Handle OTP verification
#         if not st.session_state.get('otp_verified', False):
#             if st.session_state.get('show_qr_code', False):
#                 st.title("Welcome! 👋")
#                 otp_uri = totp.provisioning_uri(name=user_data.get('email', ''), issuer_name="SynoGPT")
#                 qr = qrcode.make(otp_uri)
#                 qr = qr.resize((200, 200))
#                 st.image(qr, caption="Scan this QR code with your authenticator app (Recommended: Google Authenticator)")

#             st.title("Welcome to SynoptekGPT!")
#             otp_input = st.text_input("Enter the OTP from your authenticator app", type="password", key='otp_input')
#             verify_button_clicked = st.button("Verify OTP", key='verify_otp_button')

#             if verify_button_clicked:
#                 if totp.verify(otp_input):
#                     st.session_state['otp_verified'] = True
#                     st.session_state['show_qr_code'] = False
#                     # Display the welcome back message that disappears after a while
#                     message_placeholder = st.empty()
#                     message_id = str(uuid.uuid4()).replace('-', '')
#                     message_html = f'''
#                     <div id="{message_id}">
#                         <p style="color:green; font-weight:bold;">Welcome back, {name}!</p>
#                     </div>
#                     <script>
#                     setTimeout(function() {{
#                         var elem = document.getElementById('{message_id}');
#                         if(elem) {{
#                             elem.parentNode.removeChild(elem);
#                         }}
#                     }}, 5000);
#                     </script>
#                     '''
#                     message_placeholder.markdown(message_html, unsafe_allow_html=True)
#                     logging.info("User %s authenticated successfully with 2FA", username)
#                     # Proceed to the main app
#                     return True
#                 else:
#                     st.error("Invalid OTP. Please try again.")
#                     logging.warning("Invalid OTP attempt for user %s", username)
#                     return False
#         else:
#             # User is already verified
#             # Display the welcome back message that disappears after a while
#             if not st.session_state.get('welcome_message_displayed', False):
#                 message_placeholder = st.empty()
#                 message_id = str(uuid.uuid4()).replace('-', '')
#                 message_html = f'''
#                 <div id="{message_id}">
#                     <p style="color:green; font-weight:bold;">Welcome back, {name}!</p>
#                 </div>
#                 <script>
#                 setTimeout(function() {{
#                     var elem = document.getElementById('{message_id}');
#                     if(elem) {{
#                         elem.parentNode.removeChild(elem);
#                     }}
#                 }}, 5000);
#                 </script>
#                 '''
#                 message_placeholder.markdown(message_html, unsafe_allow_html=True)
#                 st.session_state['welcome_message_displayed'] = True
#             logging.info("User %s re-authenticated successfully", username)
#             return True

#     elif authentication_status == False:
#         st.write("# Welcome! 👋")
#         st.markdown("Please enter your username and password to log in.")
#         logging.warning("Failed login attempt with username: %s", username)
#         return False

#     elif authentication_status == None:
#         st.write("# Welcome! 👋")
#         st.markdown("Please enter your username and password to log in.")
#         return False

# # Sidebar code
# with st.sidebar:
#     st.image(r"./synoptek.png", width=275)
#     # Authentication widget
#     name, authentication_status, username = authenticator.login('Login', 'sidebar')

#     if authentication_status and st.session_state.get('otp_verified', False):
#         # Display conversations in the sidebar after full authentication
#         st.title("Conversations")

#         # Add "New Chat" button at the top with a unique key
#         if st.button("New Chat", key='new_chat_button'):
#             st.session_state.messages = []
#             # st.rerun()

#         # Functions to load and display conversations
#         def load_conversations():
#             try:
#                 if os.path.exists("conversations.json"):
#                     with open("conversations.json", "r") as f:
#                         return json.load(f)
#                 else:
#                     return []
#             except Exception as e:
#                 st.error("Failed to load conversations.")
#                 logging.error(f"Load Conversations Error: {e}")
#                 return []

#         def get_conversation_title(conversation):
#             for msg in conversation["messages"]:
#                 if msg["role"] == "user":
#                     title = msg["content"].strip()
#                     # Truncate title if it's too long
#                     return title[:28] + "..." if len(title) > 28 else title
#             return "Untitled Conversation"

#         conversations = load_conversations()

#         # Categorize conversations
#         today = []
#         yesterday = []
#         previous_7_days = []
#         previous_30_days = []

#         now = datetime.datetime.now()
#         for idx, convo in enumerate(reversed(conversations)):  # Reverse to show most recent first
#             try:
#                 timestamp = datetime.datetime.fromisoformat(convo["timestamp"])
#                 delta = now - timestamp
#                 if delta.days == 0:
#                     today.append((idx, convo))
#                 elif delta.days == 1:
#                     yesterday.append((idx, convo))
#                 elif delta.days <= 7:
#                     previous_7_days.append((idx, convo))
#                 elif delta.days <= 30:
#                     previous_30_days.append((idx, convo))
#             except Exception as e:
#                 logging.error(f"Error processing conversation timestamp: {e}")

#         # Display categories
#         if today:
#             st.subheader("Today")
#             for idx, convo in today:
#                 title = get_conversation_title(convo)
#                 if st.button(title, key=f"today_{idx}"):
#                     st.session_state.messages = convo["messages"]
#                     st.rerun()

#         if yesterday:
#             st.subheader("Yesterday")
#             for idx, convo in yesterday:
#                 title = get_conversation_title(convo)
#                 if st.button(title, key=f"yesterday_{idx}"):
#                     st.session_state.messages = convo["messages"]
#                     st.rerun()

#         if previous_7_days:
#             st.subheader("Previous 7 Days")
#             for idx, convo in previous_7_days:
#                 title = get_conversation_title(convo)
#                 if st.button(title, key=f"week_{idx}"):
#                     st.session_state.messages = convo["messages"]
#                     st.rerun()

#         if previous_30_days:
#             st.subheader("Previous 30 Days")
#             for idx, convo in previous_30_days:
#                 title = get_conversation_title(convo)
#                 if st.button(title, key=f"month_{idx}"):
#                     st.session_state.messages = convo["messages"]
#                     st.rerun()

#         # Add vertical space to push the welcome message and logout button to the bottom
#         st.markdown("<br><br><br><br><br><br>", unsafe_allow_html=True)
#         st.markdown("---")

#         # **Keep the "Hello, {user}" message above the logout button**
#         st.markdown(f'## Hello, *{name}*')

#         if st.button("Logout", key='logout_button'):
#             authenticator.logout('Logout', 'sidebar')
#             for key in list(st.session_state.keys()):
#                 del st.session_state[key]
#             st.rerun()
#     elif authentication_status == False:
#         st.error('Username/password is incorrect')
#     elif authentication_status == None:
#         st.warning('Please enter your username and password')

# # Call the authenticate_user function
# if authenticate_user(authentication_status, name, username):
#     # User is authenticated, proceed with the main app code

#     st.title("Synoptek-GPT! 🤖")

#     # Initialize session state for messages and model
#     if "messages" not in st.session_state:
#         st.session_state.messages = []

#     if "model" not in st.session_state:
#         st.session_state.model = "gpt-4o"

#     # User input
#     user_prompt = st.chat_input("Type here to Chat...")

#     if user_prompt:
#         # Append user's message to session state
#         st.session_state.messages.append({"role": "user", "content": user_prompt})

#         # Display previous chat messages (excluding the last message, which is the new user input)
#         for message in st.session_state.messages[:-1]:
#             with st.chat_message(message["role"]):
#                 st.markdown(message["content"])

#         # Display user's latest message
#         with st.chat_message("user"):
#             st.markdown(user_prompt)

#         # Generate assistant's response and display it as it's being generated
#         with st.chat_message("assistant"):
#             message_placeholder = st.empty()
#             full_response = ""

#             try:
#                 stream = client.chat.completions.create(
#                     model=st.session_state.model,
#                     messages=st.session_state.messages,
#                     stream=True,
#                     max_tokens=4000,
#                     temperature=0.2,
#                 )
#                 for chunk in stream:
#                     choices = getattr(chunk, 'choices', None)
#                     if choices:
#                         choice = choices[0]
#                         delta = getattr(choice, 'delta', None)
#                         if delta:
#                             token = getattr(delta, 'content', '')
#                             if token:
#                                 full_response += token
#                                 message_placeholder.markdown(full_response + "▌")
#                 message_placeholder.markdown(full_response)
#             except Exception as e:
#                 st.error("An error occurred while generating the response.")
#                 logging.error(f"API Error: {e}")
#                 full_response = "I'm sorry, but I'm unable to process your request at the moment."
#                 message_placeholder.markdown(full_response)

#         # Append assistant's response to session state
#         st.session_state.messages.append({"role": "assistant", "content": full_response})

#         # Function to save a conversation with error handling
#         def save_conversation(conversation):
#             try:
#                 conversations = load_conversations()
#                 # Append the new conversation with timestamp
#                 conversations.append({
#                     "timestamp": datetime.datetime.now().isoformat(),
#                     "messages": conversation
#                 })
#                 # Limit to the most recent 30 conversations
#                 conversations = conversations[-30:]
#                 with open("conversations.json", "w") as f:
#                     json.dump(conversations, f, indent=4)
#             except Exception as e:
#                 st.error("Failed to save conversation.")
#                 logging.error(f"Save Conversation Error: {e}")

#         # Save the conversation after each assistant response
#         save_conversation(st.session_state.messages)

#     else:
#         # If no new user input, display all messages
#         if st.session_state.messages:
#             for message in st.session_state.messages:
#                 with st.chat_message(message["role"]):
#                     st.markdown(message["content"])
#         else:
#             # Display an image or text until the user types
#             col1, col2, col3 = st.columns([1, 2, 1])
#             with col1:
#                 st.write("")
#             with col2:
#                 st.image(r"D:\Project\Quad-C\chatbot.png", width=375)
#             with col3:
#                 st.write("")
#             # Optionally, center the welcome text as well
#             st.markdown(
#                 "<h4 style='text-align: center;'>Welcome to SynoptekGPT! Here you will be able to try out multiple models.</h4>",
#                 unsafe_allow_html=True
#             )

# else:
#     # Stop the app if not authenticated
#     st.stop()



